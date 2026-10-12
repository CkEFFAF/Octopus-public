Octop green portable package
============================

Extract this zip anywhere. It includes a portable CPython runtime and Octop
dependencies. No system Python install is required.

Device first-run (primary, 0006 / 0007)
--------------------------------------
  Windows: double-click open-device.bat
  Linux:   ./open-device.sh

Default server is https://octop.effaf.me (editable in the wizard or via
OCTOP_DEVICE_SERVER / --server). Enter account username and password; the
client auto-enrolls (0004) and stays connected. Name / shared folders / fine
permissions are configured later on the manager (0005). Later launches
reconnect without login.


Filing-period transition (0010)
-------------------------------
Product / package default remains https://octop.effaf.me (no IP in constants).

Before domain filing completes, use either:
  - set OCTOP_DEVICE_SERVER=http://111.228.42.228:8188 then run open-device
  - or double-click open-device-transition.bat (Windows) / ./open-device-transition.sh (Linux)

That wrapper only sets the env var; scoped allow-insecure applies to this hub only.
After filing: unset OCTOP_DEVICE_SERVER (or use plain open-device) for HTTPS default.

No system Python, uv, or Node is required. Keep this folder writable so
device-state can be created beside the launchers.

Manager UI (secondary)
----------------------
  macOS / Linux:  ./start.sh
  Windows UI:     open.bat (starts in background and opens your browser)
  Windows logs:   start.bat (foreground)

Defaults: http://127.0.0.1:8088   data dir = ./data (OCTOP_HOME)

  ./start.sh --home /path/to/data --host 127.0.0.1 --port 8088

First launch follows the normal Octop setup wizard (create admin password).
Bind host/port are saved; later start without repeating --host or --port.
0.0.0.0 is a listening address. Open 127.0.0.1 on this computer, or its real
LAN/VPN IP from another computer. Configure trusted HTTPS for remote use.
Windows manager login startup (explicit opt-in):
  open.bat --install-startup
  open.bat --startup-status
  open.bat --remove-startup
These use the current data dir; add --home DATA_DIR if you use another profile.

Join with pairing code / access key (advanced CLI)
--------------------------------------------------
On the signed-in control center open Devices -> Pair device. Then run:
  Windows: start-device.bat
  Linux:   ./start-device.sh
First launch asks for the manager URL, device name, permission profile and shared
folder. Confirm the displayed permissions, then enter the pairing code or access
key in the hidden prompt. It saves an independent identity and connects immediately.
Later launches use saved identities and permissions without another login.
No startup task is installed by this guide. Linux does not offer desktop capture.

For scripted enrollment, generate an access key, save it in a private UTF-8 file:
  Windows: start-device.bat --server HTTPS_URL --key-file KEY_FILE --share SHARED_DIR
  Linux:   ./start-device.sh --server HTTPS_URL --key-file KEY_FILE --share SHARED_DIR
Or use the single-use --pair-code shown under Devices -> Pair device.
Add --desktop to view the desktop, --control to allow input, and --allow-command
only when you want individually confirmed commands. Keep this client running.
Later, run start-device.bat / ./start-device.sh without arguments to reconnect.
The client keeps its independent credential in device-state; not your login key.
Android/iOS: open the same HTTPS control center and select Key login.
Revoke a login key under Access keys; revoke enrolled devices in the device list.

Simpler guided setup / multiple trusted Windows managers
------------------------------------------------------
  Windows: setup-device.bat
  Linux:   ./setup-device.sh
The guide hides key input and asks separately for shared folders, write access,
desktop/input and commands. Linux needs no display or browser for file/command use.
Run setup again to add another independent Windows manager. Each manager needs
its own account enrollment key; same username does not synchronize databases.
All saved managers reconnect when you run start-device without arguments.
Shutting down one manager does not remove connections to other trusted managers.
Projects, chats and operation ledgers remain on the manager that created them.
No command is replayed or migrated automatically after a connection interruption.

  Windows: setup-device.bat controllers
           setup-device.bat autostart install
           setup-device.bat autostart status
           setup-device.bat autostart remove
  Linux:   ./setup-device.sh controllers
           ./setup-device.sh autostart install
           ./setup-device.sh autostart status
           ./setup-device.sh autostart remove
Windows autostart runs after OS login under that user (no OS password saved).
Linux uses a systemd user service. For boot/logout persistence enable lingering:
  sudo loginctl enable-linger YOUR_LINUX_USERNAME
Neither installer changes your firewall, TLS certificate trust or permissions.
Remote HTTP --allow-insecure is an explicit unencrypted development exception.

Move the SAME manager to another Windows computer
------------------------------------------------
  Double-click move-manager.bat for the Chinese guided export / restore.
  Export: stop the source manager and close its browser sessions first. Select
  1, enter its existing data directory, a NEW .octopmove file and a hidden
  password (12+ characters). This includes chats, credentials and local files.
  Keep the password separate from the encrypted archive, outside shared roots.
  Restore: on the new machine select 2, a NEW data directory and the archive.
  Use the same password. No existing home is overwritten or service started.
  Then open.bat --home NEW_DATA_DIR after shutting down the source instance.
  Verify the old account and data; do not run two writable copies concurrently.
  Reconfirm task execution after workspace paths change. Browser website logins
  protected by Windows/Chrome may require a new login on the destination.
  External workspaces, PostgreSQL and cross-OS migration are not included.

  Advanced export: move-manager.bat move-export --home SOURCE -o MOVE_FILE
  Advanced restore: move-manager.bat move-import MOVE_FILE --home NEW_HOME
  Password is entered hidden; --password-file UTF8_FILE is for private automation.

  On a STOPPED client, keep its identity when the same manager has moved:
  setup-device.bat relocate-controller CONTROLLER_ID --from-server OLD_URL --server NEW_URL
  Linux: ./setup-device.sh relocate-controller CONTROLLER_ID --from-server OLD_URL --server NEW_URL
  Trust the new address first. The command is offline and never probes with a
  credential. HTTP relocation needs explicit --allow-insecure; remote HTTPS
  cannot be downgraded to HTTP. Independent new managers require add-controller.
  Restart start-device / systemd after the manager and its address are verified.

Layout
------
  runtime/     portable CPython
  packages/    Octop + locked dependencies (site-packages)
  launch.py    entry bootstrap (loads packages/ + Windows pywin32 DLLs)
  open-device.bat / open-device.sh   device first-run (primary)
  start-device.bat / start-device.sh
  setup-device.bat / setup-device.sh
  start.sh / start.bat / open.bat   manager UI (secondary)
  README.txt
  VERSION.txt

Notes
-----
  Do not set PYTHONPATH=packages. Always start via open-device / start-device /
  start.sh / start.bat / launch.py so .pth files (pywin32) are processed.

  macOS: if Gatekeeper quarantines the unzipped folder:

    xattr -dr com.apple.quarantine .

Windows: if import pywintypes fails, rebuild from a current
  green package (launch.py + pywin32 DLL copy). Do not set PYTHONPATH manually.
