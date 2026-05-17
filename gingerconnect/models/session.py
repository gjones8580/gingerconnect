from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gingerconnect.models.connection import Connection


class SessionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class Session:
    connection: Connection
    state: SessionState = SessionState.CONNECTING
    process: Optional[Any] = None    # QProcess for RDP
    ssh_conn: Optional[Any] = None   # SSHConnection for SSH
    ssh_thread: Optional[Any] = None # _SSHConnectThread while connecting
    tab_index: int = -1
    error_message: str = ""
