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
            # CyberArk's MFA-method selection screen is a static interstitial that
            # the connector draws once and never updates. FreeRDP 3.x's RDP8
            # graphics pipeline (GFX) leaves such a frame black until the next
            # server update forces a repaint, so it never renders. Disabling GFX,
            # forcing software GDI, and 16bpp makes the connector fall back to
            # plain bitmap updates that paint immediately. See FreeRDP #4371/#10864.
            "-gfx",
            "/gdi:sw",
            "/bpp:16",
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
