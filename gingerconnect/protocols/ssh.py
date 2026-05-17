from __future__ import annotations
import threading
import time
from typing import Callable, Optional, Sequence

import paramiko

from gingerconnect.models.connection import Connection


def build_command_str(connection: Connection) -> str:
    t = connection.target
    s = connection.sia
    if connection.mode == "sia":
        target_part = f"{t.username}@{t.host}" if t.username else t.host
        if t.network:
            target_part += f"#{t.network}"
        user = f"{s.identity}#{s.subdomain}@{target_part}"
        return f"ssh {user}@{s.subdomain}.ssh.cyberark.cloud"
    return f"ssh {t.username}@{t.host}"


InteractiveHandler = Callable[[str, str, Sequence[tuple[str, bool]]], list[str]]


class SSHConnection:
    """
    Two-phase lifecycle:
      1. connect() — blocking, may raise paramiko.AuthenticationException or socket errors
      2. start_io() — non-blocking, starts background reader thread
    """

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._client: Optional[paramiko.SSHClient] = None
        self._channel: Optional[paramiko.Channel] = None
        self._running = False

    def connect(
        self,
        cols: int = 80,
        rows: int = 24,
        password: Optional[str] = None,
        interactive_handler: Optional[InteractiveHandler] = None,
    ) -> None:
        """
        Establish SSH connection and open a PTY shell.

        Tries auth in order: SSH agent → key files → password (if supplied) →
        keyboard-interactive (if interactive_handler supplied).

        Raises paramiko.AuthenticationException if all methods fail.
        """
        t = self.connection.target
        s = self.connection.sia

        if self.connection.mode == "sia":
            host = f"{s.subdomain}.ssh.cyberark.cloud"
            target_part = f"{t.username}@{t.host}" if t.username else t.host
            if t.network:
                target_part += f"#{t.network}"
            username = f"{s.identity}#{s.subdomain}@{target_part}"
        else:
            host = t.host
            username = t.username

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        auth_exc: Optional[paramiko.AuthenticationException] = None

        # ── attempt 1: agent + key files (+ password if given) ────────────
        # Skip agent/key lookup when:
        #   - a password was supplied (already failed on a previous attempt)
        #   - an interactive_handler is supplied (SIA kbd-int only gateway)
        use_key_auth = password is None and interactive_handler is None
        try:
            client.connect(
                host,
                username=username,
                password=password,
                look_for_keys=use_key_auth,
                allow_agent=use_key_auth,
                timeout=30,
                auth_timeout=30,
            )
        except paramiko.AuthenticationException as e:
            auth_exc = e
        except paramiko.SSHException as e:
            # paramiko 5+ raises bare SSHException("No authentication methods
            # available") instead of AuthenticationException in some paths.
            # Only normalise that specific message; let everything else
            # (BadHostKeyException, connection reset, etc.) propagate as-is.
            if "no authentication methods" in str(e).lower():
                auth_exc = paramiko.AuthenticationException(str(e))
            else:
                raise
        except Exception:
            raise  # Network / connection errors — propagate immediately

        # ── attempt 2: keyboard-interactive ───────────────────────────────
        # Used for two cases:
        #   a) interactive_handler supplied — SIA gateway sends CyberArk
        #      Identity + MFA challenges that the handler relays to the user.
        #   b) password supplied — some direct servers advertise only
        #      keyboard-interactive; respond to every prompt with the password.
        if auth_exc is not None:
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                try:
                    if interactive_handler is not None:
                        transport.auth_interactive(username, interactive_handler)
                        auth_exc = None
                    elif password is not None:
                        pw = password
                        transport.auth_interactive(
                            username,
                            lambda title, instructions, prompt_list: [pw] * len(prompt_list),
                        )
                        auth_exc = None
                except paramiko.AuthenticationException as e:
                    auth_exc = e
                except Exception as e:
                    auth_exc = paramiko.AuthenticationException(str(e))

        if auth_exc is not None:
            try:
                client.close()
            except Exception:
                pass
            raise auth_exc

        self._client = client

        transport = self._client.get_transport()
        assert transport is not None
        self._channel = transport.open_session()
        self._channel.get_pty(term="xterm-256color", width=cols, height=rows)
        self._channel.invoke_shell()

    def start_io(
        self,
        on_data: Callable[[bytes], None],
        on_close: Callable[[], None],
    ) -> None:
        """Start background reader thread. Call after connect()."""
        self._running = True
        threading.Thread(
            target=self._read_loop,
            args=(on_data, on_close),
            daemon=True,
        ).start()

    def _read_loop(
        self,
        on_data: Callable[[bytes], None],
        on_close: Callable[[], None],
    ) -> None:
        assert self._channel is not None
        while self._running:
            if self._channel.recv_ready():
                data = self._channel.recv(4096)
                if data:
                    on_data(data)
                else:
                    break
            elif self._channel.exit_status_ready():
                break
            else:
                time.sleep(0.01)
        self._running = False
        on_close()

    def write(self, data: bytes) -> None:
        if self._channel and not self._channel.closed:
            self._channel.send(data)

    def resize(self, cols: int, rows: int) -> None:
        if self._channel:
            try:
                self._channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        if self._channel:
            try:
                self._channel.close()
            except Exception:
                pass
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
