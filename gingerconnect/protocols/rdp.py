from __future__ import annotations
from gingerconnect.models.connection import Connection


def build_command(
    connection: Connection,
    settings: dict[str, str],
    password: str = "",
) -> list[str]:
    t = connection.target
    s = connection.sia

    if connection.mode == "sia":
        u_val = f"secureaccess /i {s.identity} /s {s.subdomain} /a {t.host}"
        if t.username:
            u_val += f" /u {t.username}"
        if t.domain:
            u_val += f" /d {t.domain}"
        cmd = [
            "xfreerdp3",
            f"/v:{s.subdomain}.rdp.cyberark.cloud",
            f"/u:{u_val}",
            f"/gateway:g:{s.subdomain}.rdp.cyberark.cloud:443,access-token:secureaccess,type:http",
            "/sec:tls",
            "/tls:seclevel:0",
            "/cert:ignore",
            "+clipboard",
            "/dynamic-resolution",
        ]
    else:
        cmd = [
            "xfreerdp3",
            f"/v:{t.host}",
            f"/u:{t.username}",
        ]
        if t.domain:
            cmd.append(f"/d:{t.domain}")
        cmd += ["/cert:ignore", "+clipboard", "/dynamic-resolution"]

    if password:
        cmd.append(f"/p:{password}")

    return cmd
