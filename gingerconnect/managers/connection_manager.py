from __future__ import annotations
import tomllib
import tomli_w
from copy import deepcopy
from pathlib import Path
from typing import Any

from gingerconnect.models.connection import Connection

CONFIG_DIR = Path.home() / ".config" / "gingerconnect"
CONFIG_FILE = CONFIG_DIR / "connections.toml"

DEFAULT_SETTINGS: dict[str, str] = {
    "gateway_username": "secureaccess@cyberark",
    "gateway_password": "secureaccess",
}


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[Connection] = []
        self._settings: dict[str, str] = dict(DEFAULT_SETTINGS)
        self._groups: list[str] = []
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not CONFIG_FILE.exists():
            self._save()
            return
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        self._settings = {**DEFAULT_SETTINGS, **data.get("settings", {})}
        self._connections = [Connection.from_dict(c) for c in data.get("connections", [])]
        raw = data.get("groups", [])
        self._groups = raw if isinstance(raw, list) else []
        # Ensure every connection group is represented
        for c in self._connections:
            if c.group and c.group not in self._groups:
                self._groups.append(c.group)

    def _save(self) -> None:
        data: dict[str, Any] = {
            "settings": self._settings,
            "groups": self._groups,
            "connections": [c.to_dict() for c in self._connections],
        }
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(data, f)

    @property
    def connections(self) -> list[Connection]:
        return list(self._connections)

    @property
    def settings(self) -> dict[str, str]:
        return dict(self._settings)

    @property
    def groups(self) -> list[str]:
        return list(self._groups)

    def add_group(self, name: str) -> None:
        if name not in self._groups:
            self._groups.append(name)
            self._save()

    def remove_group(self, name: str) -> bool:
        """Remove a group. Returns False if it contains connections or child groups."""
        prefix = name + "/"
        if any(c.group == name or c.group.startswith(prefix) for c in self._connections):
            return False
        if any(g.startswith(prefix) for g in self._groups):
            return False
        if name in self._groups:
            self._groups.remove(name)
            self._save()
        return True

    def rename_group(self, old: str, new: str) -> None:
        prefix = old + "/"
        self._groups = [
            new if g == old else (new + g[len(old):] if g.startswith(prefix) else g)
            for g in self._groups
        ]
        for c in self._connections:
            if c.group == old:
                c.group = new
            elif c.group.startswith(prefix):
                c.group = new + c.group[len(old):]
        self._save()

    def add(self, connection: Connection) -> None:
        self._connections.append(connection)
        self._save()

    def update(self, connection: Connection, updated: Connection) -> None:
        idx = self._connections.index(connection)
        self._connections[idx] = updated
        self._save()

    def delete(self, connection: Connection) -> None:
        self._connections.remove(connection)
        self._save()

    def duplicate(self, connection: Connection) -> Connection:
        new_conn = deepcopy(connection)
        new_conn.name = f"{connection.name} (Copy)"
        self._connections.append(new_conn)
        self._save()
        return new_conn

    def update_settings(self, settings: dict[str, str]) -> None:
        self._settings.update(settings)
        self._save()
