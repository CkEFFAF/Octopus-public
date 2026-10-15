"""Portable headless import contract; these tests do not claim native Linux support."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def device_payload(tmp_path: Path, repo_root: Path) -> Path:
    """Assemble the real allowlist without the development environment's site-packages."""
    script = (repo_root / "desktop/portable/package-device-linux.sh").read_text(encoding="utf-8")
    modules_match = re.search(r"^MODULES=\(\n(.*?)\n\)", script, re.MULTILINE | re.DOTALL)
    launch_match = re.search(
        r"cat > \"\$\{PAYLOAD\}/launch\.py\" <<'PYTHON'\n(.*?)\nPYTHON",
        script,
        re.DOTALL,
    )
    assert modules_match is not None and launch_match is not None
    payload = tmp_path / "portable device"
    packages = payload / "packages"
    for module in modules_match.group(1).split():
        relative = Path(module)
        assert relative.suffix == ".py" and ".." not in relative.parts
        source = repo_root / "src/octop" / relative
        target = packages / "octop" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    data_match = re.search(r"^DATA_FILES=\((.*?)\)", script, re.MULTILINE)
    assert data_match is not None
    for data in data_match.group(1).split():
        relative = Path(data)
        assert relative.suffix == ".json" and ".." not in relative.parts
        shutil.copyfile(repo_root / "src/octop" / relative, packages / "octop" / relative)
    for dependency in ("click", "websockets", "psutil", "yaml"):
        spec = importlib.util.find_spec(dependency)
        assert spec is not None and spec.origin is not None
        shutil.copytree(
            Path(spec.origin).parent,
            packages / dependency,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", *([] if dependency == "psutil" else ["*.pyd", "*.so"])
            ),
        )
    (payload / "launch.py").write_text(launch_match.group(1) + "\n", encoding="utf-8")
    return payload


def _isolated_python(payload: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    # -I -S excludes both repository sources and every installed application dependency.
    # Extensions are excluded too: websockets must work with its portable Python fallback.
    return subprocess.run(
        [sys.executable, "-I", "-S", "-X", "utf8", *arguments],
        cwd=payload,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["device", "--help"],
        ["device", "add-controller", "--help"],
        ["device", "run", "--help"],
        ["device", "controllers", "--help"],
        ["device", "setup", "--help"],
        ["device", "join", "--help"],
        ["device", "autostart", "install", "--help"],
        ["device", "autostart", "remove", "--help"],
    ],
)
def test_device_only_portable_commands_import_without_full_app(
    device_payload: Path, arguments: list[str]
) -> None:
    result = _isolated_python(device_payload, [str(device_payload / "launch.py"), *arguments])
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout


def test_portable_autostart_preserves_its_minimal_launcher(device_payload: Path) -> None:
    code = """
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / 'packages'))
from octop.infra.devices.autostart import runtime_command
print(json.dumps(runtime_command(root / 'device-state')))
"""
    result = _isolated_python(device_payload, ["-c", code, str(device_payload)])
    assert result.returncode == 0, result.stderr
    command = json.loads(result.stdout)
    assert Path(command[1]) == device_payload / "launch.py"
    assert command[2:5] == ["device", "run", "--state"]
    assert Path(command[5]) == device_payload / "device-state"


def test_native_desktop_import_does_not_require_controller_install_services(
    device_payload: Path,
) -> None:
    code = """
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / 'packages'))
from octop.infra.devices.desktop import DeviceDesktop
assert 'octop.infra.desktop.setup' not in sys.modules
assert DeviceDesktop.__name__ == 'DeviceDesktop'
"""
    result = _isolated_python(device_payload, ["-c", code, str(device_payload)])
    assert result.returncode == 0, result.stderr


def test_headless_payload_does_not_include_controller_or_account_modules(
    device_payload: Path,
) -> None:
    octop = device_payload / "packages/octop"
    assert not (octop / "api").exists()
    assert not (octop / "dashboard").exists()
    assert not (octop / "infra/db").exists()
    assert not (octop / "infra/users").exists()
    assert not (octop / "infra/server.py").exists()
    assert not (device_payload / "device-state").exists()
    # The minimal registry cannot accidentally boot an independent account server.
    result = _isolated_python(device_payload, [str(device_payload / "launch.py"), "run"])
    assert result.returncode == 2
    assert "No such command 'run'" in result.stderr


@pytest.mark.parametrize("unsafe_name", [None, "python/../../escape"])
def test_cross_archive_preserves_linux_runtime_links_and_rejects_escape(
    tmp_path: Path, repo_root: Path, unsafe_name: str | None
) -> None:
    script = (repo_root / "desktop/portable/package-device-linux.sh").read_text(encoding="utf-8")
    packing = re.search(r"<<'ARCHIVE_PYTHON'\n(.*?)\nARCHIVE_PYTHON", script, re.DOTALL)
    assert packing is not None
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "setup-device.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (payload / "websockets.exe").write_bytes(b"unused Windows console launcher")
    runtime = tmp_path / "pbs.tar.gz"
    with tarfile.open(runtime, "w:gz") as output:
        binary = tarfile.TarInfo(unsafe_name or "python/bin/python3.12")
        content = b"test Linux binary data"
        binary.size = len(content)
        binary.mode = 0o755
        output.addfile(binary, io.BytesIO(content))
        link = tarfile.TarInfo("python/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.12"
        output.addfile(link)
        unused_windows_stub = tarfile.TarInfo("python/lib/pip/_vendor/distlib/t64.exe")
        unused_windows_stub.size = 4
        output.addfile(unused_windows_stub, io.BytesIO(b"stub"))
    archive = tmp_path / "device.tar.gz"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            packing.group(1),
            str(payload),
            "Octop-device-linux-amd64",
            str(archive),
            str(runtime),
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )
    if unsafe_name is not None:
        assert result.returncode != 0
        assert "Unsafe or unexpected PBS archive member" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    with tarfile.open(archive) as packed:
        binary = packed.getmember("Octop-device-linux-amd64/runtime/bin/python3.12")
        assert binary.mode == 0o755
        link = packed.getmember("Octop-device-linux-amd64/runtime/bin/python3")
        assert link.issym() and link.linkname == "python3.12"
        setup = packed.getmember("Octop-device-linux-amd64/setup-device.sh")
        assert setup.mode == 0o755
        assert all(info.uid == 0 and not info.uname for info in packed)
        assert not any(info.name.endswith(".exe") for info in packed)
