#!/usr/bin/env bash
# Installs GingerConnect as a desktop application so it appears in the app
# launcher and can be pinned to the taskbar.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

mkdir -p "$APP_DIR" "$ICON_DIR"

# ── Icon ──────────────────────────────────────────────────────────────────────
cp "$SCRIPT_DIR/GingerConnect.png" "$ICON_DIR/gingerconnect.png"

# ── Desktop entry ─────────────────────────────────────────────────────────────
cat > "$APP_DIR/gingerconnect.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=GingerConnect
Comment=RDP/SSH Connection Manager with CyberArk SIA support
Exec=$SCRIPT_DIR/run.sh
Icon=gingerconnect
Terminal=false
Categories=Network;RemoteAccess;
StartupNotify=true
StartupWMClass=GingerConnect
EOF

chmod +x "$APP_DIR/gingerconnect.desktop"

# ── Refresh caches ────────────────────────────────────────────────────────────
update-desktop-database "$APP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo ""
echo "GingerConnect installed successfully."
echo ""
echo "To pin to your taskbar:"
echo "  KDE Plasma : find GingerConnect in the app launcher → right-click → Pin to Task Manager"
echo "  GNOME      : find GingerConnect in Activities → right-click → Pin to Dash"
echo "  XFCE       : right-click the panel → Panel → Add New Items → find GingerConnect"
