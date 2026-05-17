from __future__ import annotations
import shutil
import threading
from typing import Optional

import paramiko
from PyQt6.QtCore import Qt, QPoint, QProcess, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QInputDialog, QLineEdit, QMainWindow, QMenu, QSplitter,
    QStatusBar, QWidget,
)

from gingerconnect.managers.connection_manager import ConnectionManager
from gingerconnect.managers.session_manager import SessionManager
from gingerconnect.models.connection import Connection
from gingerconnect.models.session import Session, SessionState
from gingerconnect.protocols import rdp as rdp_proto
from gingerconnect.protocols.ssh import SSHConnection
from gingerconnect.sidebar import Sidebar
from gingerconnect.session_tabs import SessionTabs, RdpPlaceholder
from gingerconnect.terminal_widget import TerminalWidget
from gingerconnect.connection_dialog import ConnectionDialog
from gingerconnect.settings_dialog import SettingsDialog


# ── SSH connection thread ──────────────────────────────────────────────────────
#
# Runs paramiko auth in a worker thread so the Qt event loop stays alive.
# When a password is needed the thread pauses and emits password_needed;
# the main thread shows a dialog then calls provide_password() or cancel().

class _SSHConnectThread(QThread):
    password_needed = pyqtSignal(str)   # hint string ("" on first ask)
    kbd_challenge = pyqtSignal(str, str, list)  # title, instructions, [(prompt, echo), …]
    connected = pyqtSignal(object)      # SSHConnection
    connect_error = pyqtSignal(str)     # non-auth error message
    auth_exhausted = pyqtSignal()       # auth failed with no more retries

    def __init__(
        self,
        connection: Connection,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._connection = connection
        self._password: Optional[str] = None
        self._cancelled = False
        self._pw_event = threading.Event()
        self._kbd_responses: list[str] = []
        self._kbd_event = threading.Event()

    def provide_password(self, password: str) -> None:
        self._password = password
        self._pw_event.set()

    def provide_kbd_responses(self, responses: list[str]) -> None:
        self._kbd_responses = responses
        self._kbd_event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._pw_event.set()
        self._kbd_event.set()

    def _make_kbd_handler(self):
        """Return a blocking keyboard-interactive handler for SIA connections.

        Paramiko calls this once per auth round with the server's challenge
        prompts.  We emit kbd_challenge, park on an Event, then return the
        user's responses once the main thread calls provide_kbd_responses().
        """
        def handler(title, instructions, prompt_list):
            if self._cancelled:
                return []
            prompts = [
                (p[0] if isinstance(p, (list, tuple)) else str(p),
                 bool(p[1]) if isinstance(p, (list, tuple)) else True)
                for p in prompt_list
            ]
            self._kbd_event.clear()
            self.kbd_challenge.emit(title or "", instructions or "", prompts)
            self._kbd_event.wait()
            if self._cancelled:
                return []
            return list(self._kbd_responses)
        return handler

    def run(self) -> None:
        # ── SIA: keyboard-interactive only ────────────────────────────────
        if self._connection.mode == "sia":
            ssh = SSHConnection(self._connection)
            try:
                ssh.connect(interactive_handler=self._make_kbd_handler())
                if not self._cancelled:
                    self.connected.emit(ssh)
            except paramiko.AuthenticationException:
                if not self._cancelled:
                    self.auth_exhausted.emit()
            except Exception as exc:
                if not self._cancelled:
                    self.connect_error.emit(str(exc))
            return

        # ── Direct: password prompting (up to 3 attempts) ─────────────────
        password: Optional[str] = None
        attempt = 0
        while attempt < 3:
            attempt += 1
            ssh = SSHConnection(self._connection)
            try:
                ssh.connect(password=password)
                self.connected.emit(ssh)
                return
            except paramiko.AuthenticationException:
                if attempt >= 3:
                    self.auth_exhausted.emit()
                    return
                hint = "Wrong password — try again." if password is not None else ""
                self._pw_event.clear()
                self.password_needed.emit(hint)
                self._pw_event.wait()
                if self._cancelled:
                    return
                password = self._password
            except Exception as exc:
                self.connect_error.emit(str(exc))
                return


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GingerConnect")
        self.resize(1200, 750)

        self._conn_mgr = ConnectionManager()
        self._sess_mgr = SessionManager()

        # ── Layout ─────────────────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)

        self._sidebar = Sidebar()
        self._tabs = SessionTabs()

        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._tabs)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([220, 980])

        self.setCentralWidget(self._splitter)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        # ── Wire signals ───────────────────────────────────────────────────
        self._sidebar.connection_activated.connect(self._open_connection)
        self._sidebar.add_clicked.connect(self._add_connection)
        self._sidebar.add_group_clicked.connect(self._add_group)
        self._sidebar.settings_clicked.connect(self._show_settings)
        self._sidebar.context_menu_requested.connect(self._show_context_menu)
        self._sidebar.group_context_menu_requested.connect(self._show_group_context_menu)
        self._tabs.session_closed.connect(self._on_tab_closed)
        self._tabs.reconnect_requested.connect(self._open_connection)

        self._reload_sidebar()

    # ── Sidebar refresh ────────────────────────────────────────────────────

    def _reload_sidebar(self) -> None:
        active = {s.connection.name for s in self._sess_mgr.all()
                  if s.state == SessionState.CONNECTED}
        self._sidebar.load_connections(
            self._conn_mgr.connections, active, self._conn_mgr.groups
        )

    def _refresh_status_icons(self) -> None:
        active = {s.connection.name for s in self._sess_mgr.all()
                  if s.state == SessionState.CONNECTED}
        self._sidebar.refresh_status(active)

    # ── Open connection ────────────────────────────────────────────────────

    def _open_connection(self, connection: Connection) -> None:
        existing = self._sess_mgr.get(connection)
        if existing:
            if existing.state == SessionState.CONNECTED:
                idx = self._tabs._tab_map.get(connection.name)
                if idx is not None:
                    self._tabs.setCurrentIndex(idx)
            # Don't start a second attempt while CONNECTING
            return

        if connection.protocol == "rdp":
            self._launch_rdp(connection)
        else:
            self._launch_ssh(connection)

    # ── RDP ────────────────────────────────────────────────────────────────

    def _launch_rdp(self, connection: Connection) -> None:
        binary = shutil.which("xfreerdp3") or shutil.which("xfreerdp")
        if binary is None:
            self._status.showMessage(
                "xfreerdp3 not found in PATH. Install freerdp.", 10000
            )
            return

        # Collect password upfront so xfreerdp3 never blocks on stdin
        password = self._prompt_rdp_password(connection)
        if password is None:
            return  # user cancelled

        session = self._sess_mgr.create(connection)
        placeholder = self._tabs.open_rdp_tab(session)

        # Build display command (no password) then add /p: for execution
        display_cmd = rdp_proto.build_command(connection, self._conn_mgr.settings)
        display_cmd[0] = binary
        placeholder.set_command(display_cmd)

        exec_cmd = rdp_proto.build_command(connection, self._conn_mgr.settings, password=password)
        exec_cmd[0] = binary

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        session.process = proc
        proc.setProgram(binary)
        proc.setArguments(exec_cmd[1:])

        proc.readyReadStandardOutput.connect(
            lambda p=proc, ph=placeholder: self._on_rdp_output(p, ph)
        )
        proc.started.connect(lambda: self._on_rdp_started(session, placeholder))
        proc.finished.connect(
            lambda code, _: self._on_rdp_finished(session, placeholder, code, proc)
        )
        proc.errorOccurred.connect(
            lambda err: self._on_rdp_error(session, placeholder, err, proc)
        )

        proc.start()
        self._status.showMessage(f"Launching RDP: {connection.name}…", 5000)

    def _prompt_rdp_password(self, connection: Connection) -> Optional[str]:
        if connection.mode == "sia":
            label = f"Password for {connection.sia.identity}:"
        else:
            t = connection.target
            label = f"Password for {t.username}@{t.host}:"
        text, ok = QInputDialog.getText(
            self, f"RDP — {connection.name}", label, QLineEdit.EchoMode.Password
        )
        return text if ok else None

    def _on_rdp_output(self, proc: QProcess, placeholder: RdpPlaceholder) -> None:
        data = proc.readAllStandardOutput().data().decode(errors="replace").strip()
        if data:
            placeholder.set_output(data)

    def _on_rdp_started(self, session: Session, placeholder: RdpPlaceholder) -> None:
        session.state = SessionState.CONNECTED
        placeholder.set_status(SessionState.CONNECTED)
        self._refresh_status_icons()

    def _on_rdp_finished(
        self, session: Session, placeholder: RdpPlaceholder, code: int, proc: QProcess
    ) -> None:
        remaining = proc.readAllStandardOutput().data().decode(errors="replace").strip()
        if remaining:
            placeholder.set_output(remaining)
        session.state = SessionState.DISCONNECTED
        placeholder.set_status(SessionState.DISCONNECTED)
        self._sess_mgr.remove(session.connection)
        self._refresh_status_icons()
        self._status.showMessage(
            f"RDP ended: {session.connection.name} (exit {code})", 6000
        )

    def _on_rdp_error(
        self, session: Session, placeholder: RdpPlaceholder,
        err: QProcess.ProcessError, proc: QProcess
    ) -> None:
        remaining = proc.readAllStandardOutput().data().decode(errors="replace").strip()
        label = {
            QProcess.ProcessError.FailedToStart: "Failed to start — binary missing or not executable",
            QProcess.ProcessError.Crashed: "Process crashed",
            QProcess.ProcessError.Timedout: "Timed out waiting to start",
        }.get(err, f"Process error ({err})")
        session.state = SessionState.ERROR
        placeholder.set_status(SessionState.ERROR, label)
        if remaining:
            placeholder.set_output(remaining)
        self._sess_mgr.remove(session.connection)
        self._refresh_status_icons()
        self._status.showMessage(f"RDP error: {session.connection.name} — {label}", 10000)

    # ── SSH ────────────────────────────────────────────────────────────────

    def _launch_ssh(self, connection: Connection) -> None:
        session = self._sess_mgr.create(connection)
        session.state = SessionState.CONNECTING
        self._status.showMessage(f"Connecting SSH: {connection.name}…", 0)

        thread = _SSHConnectThread(connection, self)
        session.ssh_thread = thread

        thread.password_needed.connect(
            lambda hint, c=connection, t=thread, s=session:
                self._on_ssh_password_needed(c, t, s, hint)
        )
        thread.kbd_challenge.connect(
            lambda title, instructions, prompts, c=connection, t=thread, s=session:
                self._on_ssh_kbd_challenge(c, t, s, title, instructions, prompts)
        )
        thread.connected.connect(
            lambda ssh, s=session: self._on_ssh_connected(s, ssh)
        )
        thread.connect_error.connect(
            lambda msg, s=session, c=connection: self._on_ssh_connect_error(s, c, msg)
        )
        thread.auth_exhausted.connect(
            lambda s=session, c=connection: self._on_ssh_auth_exhausted(s, c)
        )
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_ssh_password_needed(
        self, connection: Connection, thread: _SSHConnectThread,
        session: Session, hint: str,
    ) -> None:
        title = f"SSH — {connection.name}"
        t = connection.target
        label = f"Password for {t.username}@{t.host}:"
        if hint:
            label = f"{hint}\n\n{label}"
        text, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Password)
        if not ok:
            thread.cancel()
            self._sess_mgr.remove(connection)
            self._status.clearMessage()
        else:
            thread.provide_password(text)

    def _on_ssh_kbd_challenge(
        self,
        connection: Connection,
        thread: _SSHConnectThread,
        session: Session,
        title: str,
        instructions: str,
        prompts: list,
    ) -> None:
        """Handle a keyboard-interactive challenge round from the SSH server.

        Prompts is a list of (prompt_text, echo) tuples.  We show each prompt
        in a separate dialog and collect responses before unblocking the thread.
        """
        responses: list[str] = []
        dlg_title = f"SSH — {connection.name}"

        for prompt_text, echo in prompts:
            label = prompt_text.strip() or "Response:"
            if instructions:
                label = f"{instructions.strip()}\n\n{label}"
            echo_mode = QLineEdit.EchoMode.Normal if echo else QLineEdit.EchoMode.Password
            text, ok = QInputDialog.getText(self, dlg_title, label, echo_mode)
            if not ok:
                thread.cancel()
                self._sess_mgr.remove(connection)
                self._status.clearMessage()
                return
            responses.append(text)

        thread.provide_kbd_responses(responses)

    def _on_ssh_connected(self, session: Session, ssh: SSHConnection) -> None:
        session.ssh_conn = ssh
        session.ssh_thread = None

        terminal = TerminalWidget(ssh)
        terminal.connection_closed.connect(
            lambda err, s=session: self._on_ssh_closed(s, err)
        )

        session.state = SessionState.CONNECTED
        self._tabs.open_ssh_tab(session, terminal)
        self._refresh_status_icons()
        self._status.showMessage(f"Connected: {session.connection.name}", 3000)

    def _on_ssh_connect_error(self, session: Session, connection: Connection, msg: str) -> None:
        session.ssh_thread = None
        self._sess_mgr.remove(connection)
        self._status.showMessage(f"SSH error: {connection.name} — {msg}", 10000)

    def _on_ssh_auth_exhausted(self, session: Session, connection: Connection) -> None:
        session.ssh_thread = None
        self._sess_mgr.remove(connection)
        if connection.mode == "sia":
            msg = (
                f"SSH auth failed: {connection.name} — "
                f"check CyberArk Identity credentials for {connection.sia.identity}"
            )
            self._status.showMessage(msg, 12000)
        else:
            self._status.showMessage(f"SSH auth failed: {connection.name}", 8000)

    def _on_ssh_closed(self, session: Session, error: str) -> None:
        session.state = SessionState.DISCONNECTED if not error else SessionState.ERROR
        self._sess_mgr.remove(session.connection)
        self._refresh_status_icons()
        msg = f"SSH disconnected: {session.connection.name}"
        if error:
            msg += f" — {error}"
        self._status.showMessage(msg, 6000)

    # ── Tab closed ─────────────────────────────────────────────────────────

    def _on_tab_closed(self, connection: Connection) -> None:
        session = self._sess_mgr.get(connection)
        if session:
            if session.process:
                session.process.kill()
            if session.ssh_thread and session.ssh_thread.isRunning():
                session.ssh_thread.cancel()
                session.ssh_thread.wait(2000)
            if session.ssh_conn:
                session.ssh_conn.close()
            self._sess_mgr.remove(connection)
        self._refresh_status_icons()

    # ── Group CRUD ─────────────────────────────────────────────────────────

    def _add_group(self) -> None:
        name, ok = QInputDialog.getText(self, "New Group", "Group name:")
        if ok and name.strip():
            self._conn_mgr.add_group(name.strip())
            self._reload_sidebar()

    def _show_group_context_menu(self, group_name: str, global_pos: QPoint) -> None:
        prefix = group_name + "/"
        has_content = any(
            c.group == group_name or c.group.startswith(prefix)
            for c in self._conn_mgr.connections
        ) or any(
            g.startswith(prefix) for g in self._conn_mgr.groups
        )

        menu = QMenu(self)
        sub_act = menu.addAction("Add Sub-group")
        rename_act = menu.addAction("Rename")
        menu.addSeparator()
        del_act = menu.addAction("Delete")
        del_act.setEnabled(not has_content)

        action = menu.exec(global_pos)
        if action == sub_act:
            name, ok = QInputDialog.getText(
                self, "New Sub-group",
                f"Sub-group name under '{group_name.rsplit('/', 1)[-1]}':",
            )
            if ok and name.strip():
                self._conn_mgr.add_group(f"{group_name}/{name.strip()}")
                self._reload_sidebar()
        elif action == rename_act:
            # Prompt with just the last segment; re-attach the parent prefix after
            last_segment = group_name.rsplit("/", 1)[-1]
            new_label, ok = QInputDialog.getText(
                self, "Rename Group", "New name:",
                QLineEdit.EchoMode.Normal, last_segment,
            )
            if ok and new_label.strip() and new_label.strip() != last_segment:
                parent_prefix = group_name.rsplit("/", 1)[0] + "/" if "/" in group_name else ""
                new_full = parent_prefix + new_label.strip()
                self._conn_mgr.rename_group(group_name, new_full)
                self._reload_sidebar()
        elif action == del_act and not has_content:
            self._conn_mgr.remove_group(group_name)
            self._reload_sidebar()

    # ── Connection CRUD ────────────────────────────────────────────────────

    def _add_connection(self) -> None:
        dlg = ConnectionDialog(self)
        if dlg.exec():
            self._conn_mgr.add(dlg.get_connection())
            self._reload_sidebar()

    def _edit_connection(self, connection: Connection) -> None:
        dlg = ConnectionDialog(self, connection=connection)
        if dlg.exec():
            self._conn_mgr.update(connection, dlg.get_connection())
            self._reload_sidebar()

    def _delete_connection(self, connection: Connection) -> None:
        session = self._sess_mgr.get(connection)
        if session:
            if session.process:
                session.process.kill()
            if session.ssh_thread and session.ssh_thread.isRunning():
                session.ssh_thread.cancel()
                session.ssh_thread.wait(2000)
            if session.ssh_conn:
                session.ssh_conn.close()
            self._sess_mgr.remove(connection)
        if self._tabs.has_tab(connection):
            self._tabs.close_tab_for(connection)
        self._conn_mgr.delete(connection)
        self._reload_sidebar()

    def _duplicate_connection(self, connection: Connection) -> None:
        self._conn_mgr.duplicate(connection)
        self._reload_sidebar()

    # ── Context menu ───────────────────────────────────────────────────────

    def _show_context_menu(self, connection: Connection, global_pos) -> None:
        menu = QMenu(self)
        connect_act = menu.addAction("Connect")
        edit_act = menu.addAction("Edit")
        menu.addSeparator()
        dup_act = menu.addAction("Duplicate")
        menu.addSeparator()
        del_act = menu.addAction("Delete")

        action = menu.exec(global_pos)
        if action == connect_act:
            self._open_connection(connection)
        elif action == edit_act:
            self._edit_connection(connection)
        elif action == dup_act:
            self._duplicate_connection(connection)
        elif action == del_act:
            self._delete_connection(connection)

    # ── Settings ───────────────────────────────────────────────────────────

    def _show_settings(self) -> None:
        SettingsDialog(self._conn_mgr, self).exec()
