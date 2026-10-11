"""Opt-in user-session startup for a saved device network (no credentials in units)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from octop.infra.devices.executor import DeviceExecutionError, _reject_links


def service_name(state: Path) -> str:
    identity = os.path.normcase(str(state.expanduser().absolute()))
    return "octop-device-" + hashlib.sha256(identity.encode()).hexdigest()[:12]


def runtime_command(state: Path) -> list[str]:
    """Preserve the portable bootstrap when running from a bundled interpreter."""
    python = Path(sys.executable).absolute()
    entry = Path(sys.argv[0]).absolute()
    # runpy changes argv[0] to packages/octop/__main__.py during the portable
    # CLI. A plain `python -m octop` would then omit packages/ on the next boot.
    package_path = Path(__file__).resolve()
    bundled_entry = package_path.parents[4] / "launch.py"
    if package_path.parents[3].name == "packages" and bundled_entry.is_file():
        entry = bundled_entry
    prefix = [str(python)]
    if entry.name == "launch.py" and entry.is_file():
        prefix.append(str(entry))
    else:
        prefix.extend(["-m", "octop"])
    return [*prefix, "device", "run", "--state", str(state.expanduser().absolute())]


def _unit_quote(value: str) -> str:
    if any(c in value for c in ("\n", "\r", "\0")):
        raise DeviceExecutionError("invalid startup path")
    # systemd specifiers and environment expansion are not shell quoting.
    return (
        '"'
        + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
    )


def systemd_unit(command: list[str]) -> str:
    return (
        "[Unit]\nDescription=Octop device network\nAfter=network-online.target\n\n"
        "[Service]\nType=simple\nExecStart="
        + " ".join(_unit_quote(value) for value in command)
        + "\nRestart=on-failure\nRestartSec=5\nUMask=0077\n\n"
        "[Install]\nWantedBy=default.target\n"
    )


def windows_task(command: list[str], user_sid: str) -> str:
    if not user_sid.startswith("S-1-") or not all(c.isdigit() or c in "S-" for c in user_sid):
        raise DeviceExecutionError("cannot identify startup account")
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    root = ET.Element("Task", {"version": "1.2", "xmlns": namespace})

    def element(parent: ET.Element, name: str, value: str | None = None) -> ET.Element:
        child = ET.SubElement(parent, name)
        child.text = value
        return child

    trigger = element(element(root, "Triggers"), "LogonTrigger")
    element(trigger, "Enabled", "true")
    element(trigger, "UserId", user_sid)
    principal = element(element(root, "Principals"), "Principal")
    principal.set("id", "Author")
    element(principal, "UserId", user_sid)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("Enabled", "true"),
        ("Hidden", "true"),
        ("ExecutionTimeLimit", "PT0S"),
    ):
        element(settings, name, value)
    restart = element(settings, "RestartOnFailure")
    element(restart, "Interval", "PT1M")
    element(restart, "Count", "999")
    actions = element(root, "Actions")
    actions.set("Context", "Author")
    execute = element(actions, "Exec")
    executable = Path(command[0])
    windowless = executable.with_name("pythonw.exe")
    element(execute, "Command", str(windowless if windowless.is_file() else executable))
    element(execute, "Arguments", subprocess.list2cmdline(command[1:]))
    element(execute, "WorkingDirectory", str(executable.parent))
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeviceExecutionError("startup command unavailable: " + command[0]) from exc
    if result.returncode:
        raise DeviceExecutionError("startup command failed: " + " ".join(command[:2]))
    return result


def startup_path(state: Path) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / (service_name(state) + ".service")


def install(state: Path, *, command: list[str] | None = None, name: str | None = None) -> str:
    command = command or runtime_command(state)
    system = platform.system()
    name = name or service_name(state)
    if system == "Windows":
        import csv

        identity = _run(["whoami", "/user", "/fo", "csv", "/nh"])
        sid = next(csv.reader([identity.stdout.strip()]))[-1]
        xml = windows_task(command, sid)
        fd, filename = tempfile.mkstemp(suffix=".xml", prefix="octop-startup-")
        try:
            with os.fdopen(fd, "w", encoding="utf-16") as stream:
                stream.write(xml)
            _run(["schtasks", "/Create", "/TN", name, "/XML", filename, "/F"])
            # Start is explicit here; no need to wait for the next login.
            _run(["schtasks", "/Run", "/TN", name])
        finally:
            Path(filename).unlink(missing_ok=True)
        return f"Installed {name}; starts at Windows login under this OS user."
    if system == "Linux":
        target = startup_path(state)
        _reject_links(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(systemd_unit(command), encoding="utf-8")
        target.chmod(0o600)
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", target.name])
        return (
            f"Installed {target.name}. For headless boot/logout persistence, enable lingering "
            "for this OS user: sudo loginctl enable-linger USERNAME."
        )
    raise DeviceExecutionError("startup is supported on Windows and Linux")


def uninstall(state: Path, *, name: str | None = None) -> str:
    name = name or service_name(state)
    system = platform.system()
    if system == "Windows":
        # Removing a task prevents later launch; stop is best effort if not running.
        with contextlib.suppress(DeviceExecutionError):
            _run(["schtasks", "/End", "/TN", name])
        _run(["schtasks", "/Delete", "/TN", name, "/F"])
    elif system == "Linux":
        target = startup_path(state)
        _reject_links(target)
        _run(["systemctl", "--user", "disable", "--now", target.name])
        target.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
    else:
        raise DeviceExecutionError("startup is supported on Windows and Linux")
    return "Startup removed; saved device identities and journals are retained."


def status(state: Path, *, name: str | None = None) -> str:
    name = name or service_name(state)
    if platform.system() == "Windows":
        return _run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"]).stdout.strip()
    if platform.system() == "Linux":
        return _run(
            [
                "systemctl",
                "--user",
                "show",
                name + ".service",
                "--property=ActiveState,UnitFileState,SubState",
            ]
        ).stdout.strip()
    raise DeviceExecutionError("startup is supported on Windows and Linux")
