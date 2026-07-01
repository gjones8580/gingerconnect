from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QLabel, QTabBar, QTabWidget, QVBoxLayout, QHBoxLayout, QWidget, QPushButton,
)

from gingerconnect.models.connection import Connection
from gingerconnect.models.session import Session, SessionState


class RdpPlaceholder(QWidget):
    reconnect_requested = pyqtSignal()

    def __init__(self, session: Session, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._session = session
        self._output_lines: list[str] = []
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        conn = session.connection
        name_lbl = QLabel(conn.name or conn.target.host)
        name_lbl.setStyleSheet("font-size:20px;font-weight:bold;color:#cdd6f4;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_lbl)

        host_lbl = QLabel(conn.target.host)
        host_lbl.setStyleSheet("font-size:13px;color:#6c7086;")
        host_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(host_lbl)

        self._status_lbl = QLabel("Launching RDP session…")
        self._status_lbl.setStyleSheet("font-size:13px;color:#89b4fa;")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_lbl)

        reconnect_btn = QPushButton("Reconnect")
        reconnect_btn.setObjectName("AccentButton")
        reconnect_btn.setFixedWidth(120)
        reconnect_btn.clicked.connect(self.reconnect_requested)
        reconnect_btn.setVisible(False)
        self._reconnect_btn = reconnect_btn
        layout.addWidget(reconnect_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        cmd_lbl = QLabel()
        cmd_lbl.setStyleSheet("font-size:11px;color:#45475a;font-family:monospace;")
        cmd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cmd_lbl.setWordWrap(True)
        self._cmd_lbl = cmd_lbl
        layout.addWidget(cmd_lbl)

        output_lbl = QLabel()
        output_lbl.setStyleSheet(
            "font-size:11px;color:#f38ba8;font-family:monospace;"
            "background:#181825;border-radius:4px;padding:6px;"
        )
        output_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        output_lbl.setWordWrap(True)
        output_lbl.setVisible(False)
        output_lbl.setMaximumWidth(700)
        self._output_lbl = output_lbl
        layout.addWidget(output_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_command(self, cmd: list[str]) -> None:
        self._cmd_lbl.setText(" ".join(cmd))

    _MAX_OUTPUT_LINES = 12

    def set_output(self, text: str) -> None:
        # Accumulate the tail of FreeRDP output instead of overwriting, so a
        # failure that prints before the last chunk isn't lost. QProcess hands
        # us arbitrary chunks, so split on newlines and keep the last N lines.
        new_lines = [ln for ln in text.splitlines() if ln.strip()]
        if not new_lines:
            return
        self._output_lines.extend(new_lines)
        del self._output_lines[: -self._MAX_OUTPUT_LINES]
        self._output_lbl.setText("\n".join(self._output_lines))
        self._output_lbl.setVisible(True)

    def set_status(self, state: SessionState, message: str = "") -> None:
        if state == SessionState.CONNECTED:
            self._status_lbl.setText("RDP session active (external window)")
            self._status_lbl.setStyleSheet("font-size:13px;color:#a6e3a1;")
            self._reconnect_btn.setVisible(False)
            # Keep any accumulated output visible — proc.started fires as soon as
            # the process launches, well before FreeRDP reports a connection
            # failure, so hiding here would swallow late errors.
        elif state == SessionState.DISCONNECTED:
            self._status_lbl.setText("Session ended")
            self._status_lbl.setStyleSheet("font-size:13px;color:#6c7086;")
            self._reconnect_btn.setVisible(True)
        elif state == SessionState.ERROR:
            self._status_lbl.setText(f"Error: {message}")
            self._status_lbl.setStyleSheet("font-size:13px;color:#f38ba8;")
            self._reconnect_btn.setVisible(True)


class SessionTabs(QTabWidget):
    session_closed = pyqtSignal(object)   # Connection
    reconnect_requested = pyqtSignal(object)  # Connection

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._on_tab_close)

        self._tab_map: dict[str, int] = {}          # connection.name -> tab index
        self._widgets: dict[str, QWidget] = {}
        self._connections: dict[str, Connection] = {}  # connection.name -> Connection

        self._empty_label = QLabel("Double-click a connection to open a session")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color:#45475a;font-size:14px;")
        self.addTab(self._empty_label, "")
        self.tabBar().setTabButton(0, self.tabBar().ButtonPosition.RightSide, None)
        self.tabBar().setTabEnabled(0, False)

    # ── public ─────────────────────────────────────────────────────────────

    def open_rdp_tab(self, session: Session) -> RdpPlaceholder:
        conn = session.connection
        if conn.name in self._tab_map:
            self.setCurrentIndex(self._tab_map[conn.name])
            return self._widgets[conn.name]  # type: ignore[return-value]

        self._hide_empty()
        widget = RdpPlaceholder(session)
        widget.reconnect_requested.connect(lambda c=conn: self.reconnect_requested.emit(c))
        idx = self.addTab(widget, conn.name or conn.target.host)
        self._set_close_button(idx, conn.name)
        self._tab_map[conn.name] = idx
        self._widgets[conn.name] = widget
        self._connections[conn.name] = conn
        self.setCurrentIndex(idx)
        return widget

    def open_ssh_tab(self, session: Session, terminal: QWidget) -> None:
        conn = session.connection
        if conn.name in self._tab_map:
            self.setCurrentIndex(self._tab_map[conn.name])
            return

        self._hide_empty()
        idx = self.addTab(terminal, conn.name or conn.target.host)
        self._set_close_button(idx, conn.name)
        self._tab_map[conn.name] = idx
        self._widgets[conn.name] = terminal
        self._connections[conn.name] = conn
        self.setCurrentIndex(idx)
        terminal.setFocus()

    def _set_close_button(self, idx: int, conn_name: str) -> None:
        btn = QPushButton("✕")
        btn.setFixedSize(16, 16)
        btn.setObjectName("TabCloseButton")
        # Capture conn_name by value so the lookup stays correct if tabs reorder.
        btn.clicked.connect(lambda _checked=False, name=conn_name: self._close_by_name(name))
        self.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, btn)

    def _close_by_name(self, conn_name: str) -> None:
        idx = self._tab_map.get(conn_name)
        if idx is not None:
            self._on_tab_close(idx)

    def get_rdp_placeholder(self, connection: Connection) -> Optional[RdpPlaceholder]:
        w = self._widgets.get(connection.name)
        return w if isinstance(w, RdpPlaceholder) else None

    def close_tab_for(self, connection: Connection) -> None:
        name = connection.name
        if name not in self._tab_map:
            return
        idx = self._tab_map.pop(name)
        self._widgets.pop(name, None)
        self._connections.pop(name, None)
        self._reindex(idx)
        self.removeTab(idx)
        self._maybe_show_empty()

    def has_tab(self, connection: Connection) -> bool:
        return connection.name in self._tab_map

    # ── internal ───────────────────────────────────────────────────────────

    def _hide_empty(self) -> None:
        if self._empty_label.isVisible():
            self.removeTab(0)
            self._empty_label.setVisible(False)

    def _maybe_show_empty(self) -> None:
        if self.count() == 0:
            self._empty_label.setVisible(True)
            self.addTab(self._empty_label, "")
            self.tabBar().setTabButton(0, self.tabBar().ButtonPosition.RightSide, None)
            self.tabBar().setTabEnabled(0, False)

    def _reindex(self, removed_idx: int) -> None:
        for name, idx in self._tab_map.items():
            if idx > removed_idx:
                self._tab_map[name] = idx - 1

    def _on_tab_close(self, idx: int) -> None:
        conn_name = next(
            (name for name, i in self._tab_map.items() if i == idx), None
        )
        if conn_name is None:
            return

        widget = self.widget(idx)
        from gingerconnect.terminal_widget import TerminalWidget
        if isinstance(widget, TerminalWidget):
            widget.close_connection()

        conn = self._connections.get(conn_name)
        self._tab_map.pop(conn_name, None)
        self._widgets.pop(conn_name, None)
        self._connections.pop(conn_name, None)
        self._reindex(idx)
        self.removeTab(idx)
        self._maybe_show_empty()

        if conn is not None:
            self.session_closed.emit(conn)

    def currentTabConnection(self) -> Optional[Connection]:
        idx = self.currentIndex()
        name = next((n for n, i in self._tab_map.items() if i == idx), None)
        return self._connections.get(name) if name else None
