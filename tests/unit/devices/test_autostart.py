from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from octop.infra.devices import autostart
from octop.infra.devices.executor import DeviceExecutionError


def test_units_keep_paths_literal_and_credentials_out() -> None:
    argv = [
        "/opt/Octop Space/bin/python",
        "-m",
        "octop",
        "device",
        "run",
        "--state",
        '/home/a/10% $HOME/"state"',
    ]
    unit = autostart.systemd_unit(argv)
    assert '"/opt/Octop Space/bin/python"' in unit
    assert '10%% $$HOME/\\"state\\"' in unit
    assert "Restart=on-failure" in unit
    assert "UMask=0077" in unit
    assert "--key" not in unit
    with pytest.raises(DeviceExecutionError):
        autostart.systemd_unit(["python", "bad\npath"])


def test_windows_task_is_current_user_least_privilege_and_no_password() -> None:
    command = [
        r"D:\Octop Space\python.exe",
        r"D:\Octop Space\launch.py",
        "device",
        "run",
        "--state",
        r"D:\Device Private",
    ]
    root = ET.fromstring(autostart.windows_task(command, "S-1-5-21-123"))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert (
        root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    )
    assert root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns) == "LeastPrivilege"
    assert root.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert '"D:\\Device Private"' in root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns)
    assert "Password" not in ET.tostring(root, encoding="unicode")


def test_portable_startup_keeps_bootstrap_after_runpy_changes_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Octop portable"
    root.mkdir()
    entry = root / "launch.py"
    entry.write_text("# portable bootstrap", encoding="utf-8")
    python = root / "runtime" / "python.exe"
    module = root / "packages" / "octop" / "infra" / "devices" / "autostart.py"
    monkeypatch.setattr(autostart, "__file__", str(module))
    monkeypatch.setattr(autostart.sys, "argv", [str(root / "packages" / "octop" / "__main__.py")])
    monkeypatch.setattr(autostart.sys, "executable", str(python))
    state = tmp_path / "private state"
    assert autostart.runtime_command(state) == [
        str(python),
        str(entry),
        "device",
        "run",
        "--state",
        str(state),
    ]


def test_linux_install_enables_only_saved_user_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "systemd" / "network.service"
    calls: list[list[str]] = []
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setattr(autostart, "startup_path", lambda state: target)
    monkeypatch.setattr(
        autostart,
        "runtime_command",
        lambda state: ["python", "-m", "octop", "device", "run", "--state", str(state)],
    )
    monkeypatch.setattr(autostart, "_run", lambda args: calls.append(args))
    result = autostart.install(tmp_path / "private")
    assert target.is_file()
    assert ["systemctl", "--user", "enable", "--now", "network.service"] in calls
    assert "enable-linger" in result
    marker = tmp_path / "private" / "device.json"
    marker.parent.mkdir()
    marker.write_text("identity stays")
    autostart.uninstall(tmp_path / "private")
    assert not target.exists()
    assert marker.read_text() == "identity stays"
