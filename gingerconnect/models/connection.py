from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Target:
    host: str = ""
    username: str = ""
    domain: str = ""
    network: str = ""


@dataclass
class SIA:
    subdomain: str = ""
    identity: str = ""


@dataclass
class Connection:
    name: str = ""
    group: str = ""
    protocol: str = "rdp"
    mode: str = "direct"
    target: Target = field(default_factory=Target)
    sia: SIA = field(default_factory=SIA)

    def to_dict(self) -> dict[str, Any]:
        target: dict[str, Any] = {
            "host": self.target.host,
            "username": self.target.username,
        }
        if self.protocol == "rdp":
            target["domain"] = self.target.domain
        if self.mode == "sia" and self.protocol == "ssh" and self.target.network:
            target["network"] = self.target.network

        d: dict[str, Any] = {
            "name": self.name,
            "group": self.group,
            "protocol": self.protocol,
            "mode": self.mode,
            "target": target,
        }
        if self.mode == "sia":
            d["sia"] = {
                "subdomain": self.sia.subdomain,
                "identity": self.sia.identity,
            }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Connection:
        target_data = d.get("target", {})
        sia_data = d.get("sia", {})
        return cls(
            name=d.get("name", ""),
            group=d.get("group", ""),
            protocol=d.get("protocol", "rdp"),
            mode=d.get("mode", "direct"),
            target=Target(
                host=target_data.get("host", ""),
                username=target_data.get("username", ""),
                domain=target_data.get("domain", ""),
                network=target_data.get("network", ""),
            ),
            sia=SIA(
                subdomain=sia_data.get("subdomain", ""),
                identity=sia_data.get("identity", ""),
            ),
        )
