"""Remember the manager configuration and optionally open its UI without a console."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--open", action="store_true", help="Open the manager UI.")
    parser.add_argument(
        "--background", action="store_true", help="Start without keeping a console open."
    )
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument(
        "--install-startup",
        action="store_true",
        help="Install a Windows login task for this manager.",
    )
    startup.add_argument(
        "--remove-startup", action="store_true", help="Remove the Windows manager startup task."
    )
    startup.add_argument(
        "--startup-status", action="store_true", help="Show the manager startup task."
    )
    options, arguments = parser.parse_known_args()
    home = (
        (options.home or Path(os.environ.get("OCTOP_HOME", str(root / "data"))))
        .expanduser()
        .absolute()
    )
    os.environ["OCTOP_HOME"] = str(home)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ.pop("PYTHONPATH", None)
    home.mkdir(parents=True, exist_ok=True)
    if options.install_startup or options.remove_startup or options.startup_status:
        if os.name != "nt":
            print(
                "This manager startup shortcut is for Windows; Linux uses the headless device client.",
                file=sys.stderr,
            )
            return 1
        bootstrap = runpy.run_path(str(root / "launch.py"))
        bootstrap["_bootstrap"]()
        from octop.infra.devices import autostart

        name = autostart.service_name(home).replace("octop-device-", "octop-manager-")
        if options.install_startup:
            print(
                autostart.install(
                    home,
                    command=[sys.executable, str(root / "portable-start.py"), "--home", str(home)],
                    name=name,
                )
            )
        elif options.remove_startup:
            print(autostart.uninstall(home, name=name))
        else:
            print(autostart.status(home, name=name))
        return 0
    config_file = home / "config.json"
    try:
        config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        if not isinstance(config, dict):
            raise ValueError
    except (OSError, ValueError):
        print(
            "The manager config is unreadable; repair config.json before starting.", file=sys.stderr
        )
        return 1
    bind_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    bind_parser.add_argument("--host")
    bind_parser.add_argument("--port", type=int)
    bind, _ = bind_parser.parse_known_args(arguments)
    host = (
        bind.host
        or os.environ.get("OCTOP_BIND_HOST")
        or config.get("bind_host")
        or config.get("host")
        or "127.0.0.1"
    )
    port = (
        bind.port
        if bind.port is not None
        else int(os.environ.get("OCTOP_PORT") or config.get("port", 8088))
    )
    tls = config.get("tls", {})
    tls = tls if isinstance(tls, dict) else {}
    secure = "--ssl" in arguments or bool(
        tls.get("enabled") and tls.get("cert_file") and tls.get("key_file")
    )
    address = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    url = f"{'https' if secure else 'http'}://{address}:{port}"
    print(f"[octop] data={home}\n[octop] UI: {url}")
    command = [sys.executable, str(root / "launch.py"), "run", *arguments]
    if options.background:

        def available() -> bool:
            try:
                with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                    return response.status == 200
            except (OSError, urllib.error.URLError):
                return False

        process = None
        if available():
            # A healthy server at this port may belong to another data directory.
            # Reuse it only when the selected home's lifetime lock is held.
            bootstrap = runpy.run_path(str(root / "launch.py"))
            bootstrap["_bootstrap"]()
            from octop.infra.utils.process_lock import ProcessAlreadyRunning, ProcessLock

            try:
                with ProcessLock(home / ".host.lock"):
                    pass
            except ProcessAlreadyRunning:
                pass
            else:
                print(
                    "This port is used by another manager. Select its data directory or another port.",
                    file=sys.stderr,
                )
                return 1
        else:
            with (home / "launcher.log").open("ab") as log:
                kwargs = (
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs
                )
            for _ in range(30):
                if available():
                    break
                if process.poll() is not None:
                    print(f"Manager failed to start; see {home / 'launcher.log'}", file=sys.stderr)
                    return 1
                time.sleep(0.5)
            else:
                print(f"Manager is starting; see {home / 'launcher.log'}", file=sys.stderr)
                return 1
        if options.open:
            webbrowser.open(url)
        return 0
    if options.open:
        webbrowser.open(url)
    sys.argv = [str(root / "launch.py"), "run", *arguments]
    runpy.run_path(str(root / "launch.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
