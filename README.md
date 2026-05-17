# GingerConnect

A lightweight PyQt6 desktop application for managing RDP and SSH connections, with native support for **CyberArk Secure Infrastructure Access (SIA)**.

![GingerConnect](GingerConnect.png)

---

## Features

- **RDP sessions** via `xfreerdp3` — launched in an external window with clipboard sharing and dynamic resolution
- **SSH sessions** — built-in terminal emulator (pyte) rendered directly in the tab
- **CyberArk SIA** — first-class support for both SIA SSH (keyboard-interactive with MFA) and SIA RDP gateway
- **Zero Standing Privileges (ZSP)** — username field is optional for SIA connections
- **Nested groups** — organise connections into hierarchical groups using `/` as a separator (e.g. `CSSE/RDP`, `CSSE/SSH`)
- **Collapsible sidebar** — groups expand and collapse; state is preserved across reloads
- **Catppuccin Mocha** theme throughout
- **Desktop integration** — ships with an installer that registers the app with your system launcher

---

## Requirements

### System

| Dependency | Purpose |
|---|---|
| Python 3.11+ | Runtime |
| `xfreerdp3` | RDP sessions |
| A working display server | X11 or Wayland |

Install `xfreerdp3` on Arch / CachyOS:

```bash
sudo pacman -S freerdp
```

On Debian / Ubuntu:

```bash
sudo apt install freerdp3-x11
```

### Python packages

All Python dependencies are listed in `requirements.txt` and `pyproject.toml`. They are installed automatically by `run.sh` or by running `pip install -e .`.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/gingerconnect.git
cd gingerconnect
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Or install as an editable package (adds a `gingerconnect` command to the venv):

```bash
.venv/bin/pip install -e .
```

### 3. Run

```bash
./run.sh
```

`run.sh` creates the virtual environment and installs dependencies automatically if they are not already present, so steps 2 and 3 can be skipped if you prefer to just run the script directly.

### 4. Desktop integration (optional but recommended)

Register GingerConnect with your desktop environment so it appears in the application launcher and can be pinned to the taskbar:

```bash
./install.sh
```

After installation:

| Desktop Environment | How to pin |
|---|---|
| **KDE Plasma** | Find *GingerConnect* in the app launcher → right-click → *Pin to Task Manager* |
| **GNOME** | Find *GingerConnect* in Activities → right-click → *Pin to Dash* |
| **XFCE** | Right-click panel → *Panel* → *Add New Items* → find GingerConnect |

If you move the project folder, re-run `./install.sh` to update the path in the desktop entry.

---

## Configuration

Connection data is stored in:

```
~/.config/gingerconnect/connections.toml
```

This file is created automatically on first run. It contains all connection definitions and group metadata. **It is not included in the repository** and should not be committed — add your own entries via the UI.

---

## Usage

### Adding a connection

Click **+** in the sidebar and choose **Add Connection**, or right-click an existing connection and choose **Edit**.

| Field | Notes |
|---|---|
| **Name** | Display name shown in the sidebar and tab |
| **Group** | Group this connection belongs to. Use `/` for nesting, e.g. `CSSE/RDP` |
| **Protocol** | `rdp` or `ssh` |
| **Mode** | `direct` (plain TCP) or `sia` (CyberArk SIA gateway) |
| **Host** | Target hostname or IP address |
| **Username** | Account to connect as. Optional for SIA ZSP connections |
| **Domain** | Windows domain (RDP only, optional) |
| **Network** | SIA network context (SIA SSH only, optional) |

### CyberArk SIA fields (visible when Mode = `sia`)

| Field | Notes |
|---|---|
| **Subdomain** | Your CyberArk tenant subdomain (e.g. `csse`) |
| **Identity** | Your CyberArk Identity login (e.g. `user@example.cloud`) |

### Connecting

Double-click a connection in the sidebar to open a session. Right-clicking a connection shows options to Connect, Edit, Duplicate, or Delete.

### Managing groups

- **Add a top-level group:** click **+** → *Add Group*
- **Add a sub-group:** right-click an existing group → *Add Sub-group*
- **Rename a group:** right-click → *Rename* (renames child groups and all connections automatically)
- **Delete a group:** right-click → *Delete* (only available when the group is empty)
- **Collapse / expand:** click any group header in the sidebar

Group state (expanded or collapsed) is preserved when connections are added, edited, or removed.

---

## CyberArk SIA — How it works

### SSH (keyboard-interactive)

GingerConnect connects to `{subdomain}.ssh.cyberark.cloud:22` using standard SSH. The CyberArk gateway responds with keyboard-interactive challenges (CyberArk Identity credentials and MFA). GingerConnect presents each server-sent prompt in a dialog, collects your responses, and forwards them. Once authenticated, CyberArk brokers the session to the target host using its own internal public-key authentication — no additional credentials are required from you.

### RDP

GingerConnect passes a compound username to `xfreerdp3` that encodes the SIA routing information:

```
secureaccess /i <identity> /s <subdomain> /a <host> [/u <username>] [/d <domain>]
```

The session connects to `{subdomain}.rdp.cyberark.cloud:443` over TLS. GingerConnect prompts for your CyberArk Identity password before launching so that `xfreerdp3` never blocks on stdin.

### Zero Standing Privileges (ZSP)

Leave the **Username** field blank when creating a SIA connection. GingerConnect omits the `/u` flag from the SSH username string and the RDP command, allowing CyberArk to determine the target account dynamically based on your identity and authorisation policies.

---

## Project structure

```
gingerconnect/
├── gingerconnect/
│   ├── app.py                  # QApplication subclass + entry point
│   ├── main_window.py          # Main window, session orchestration
│   ├── sidebar.py              # Connection tree with nested groups
│   ├── session_tabs.py         # Tab widget for open sessions
│   ├── terminal_widget.py      # pyte-backed SSH terminal renderer
│   ├── connection_dialog.py    # Add / edit connection dialog
│   ├── settings_dialog.py      # Application settings dialog
│   ├── theme.py                # Catppuccin Mocha stylesheet
│   ├── models/
│   │   ├── connection.py       # Connection, Target, SIA dataclasses
│   │   └── session.py          # Session state model
│   ├── managers/
│   │   ├── connection_manager.py  # TOML persistence, group CRUD
│   │   └── session_manager.py    # In-memory active session registry
│   └── protocols/
│       ├── ssh.py              # paramiko SSH client wrapper
│       └── rdp.py              # xfreerdp3 command builder
├── main.py                     # CLI entry point
├── run.sh                      # Launch script (creates venv if needed)
├── install.sh                  # Desktop integration installer
├── requirements.txt            # Pinned dependency list
├── pyproject.toml              # Package metadata and build config
├── GingerConnect.png           # Application icon
└── LICENSE
```

---

## License

MIT — see [LICENSE](LICENSE).
