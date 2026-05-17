from __future__ import annotations
from typing import Optional

from gingerconnect.models.connection import Connection
from gingerconnect.models.session import Session, SessionState


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, connection: Connection) -> Session:
        session = Session(connection=connection)
        self._sessions[connection.name] = session
        return session

    def get(self, connection: Connection) -> Optional[Session]:
        return self._sessions.get(connection.name)

    def is_active(self, connection: Connection) -> bool:
        s = self._sessions.get(connection.name)
        return s is not None and s.state == SessionState.CONNECTED

    def remove(self, connection: Connection) -> None:
        self._sessions.pop(connection.name, None)

    def all(self) -> list[Session]:
        return list(self._sessions.values())
