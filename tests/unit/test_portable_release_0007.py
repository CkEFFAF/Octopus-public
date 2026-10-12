"""0007 portable Release layout / CI hard gates (static checks)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_readme_txt_primary_path_is_open_device() -> None:
    readme = (REPO / "desktop/portable/templates/README.txt").read_text(encoding="utf-8")
    assert "open-device.bat" in readme
    assert "open-device.sh" in readme
    assert "https://octop.effaf.me" in readme
    primary = readme.find("Device first-run")
    manager = readme.find("Manager UI")
    assert primary != -1 and manager != -1
    assert primary < manager, "device first-run must be documented before manager UI"


def test_package_sh_copies_device_launchers() -> None:
    script = (REPO / "desktop/portable/package.sh").read_text(encoding="utf-8")
    for name in (
        "open-device.bat",
        "open-device.sh",
        "start-device.bat",
        "start-device.sh",
        "setup-device.bat",
        "setup-device.sh",
        "README.txt",
    ):
        assert name in script


def test_package_device_linux_includes_open_device_and_kind() -> None:
    script = (REPO / "desktop/portable/package-device-linux.sh").read_text(encoding="utf-8")
    assert 'cp "${REPO_ROOT}/desktop/portable/open-device.sh"' in script
    assert "kind=headless-device-client" in script
    assert "/open-device.sh" in script  # tar mode bits


def test_octop_desktop_workflow_attaches_device_linux() -> None:
    wf = (REPO / ".github/workflows/octop-desktop.yml").read_text(encoding="utf-8")
    assert "package-device-linux:" in wf
    assert "package-device-linux.sh linux-amd64" in wf
    assert "needs: [package, package-device-linux]" in wf
    assert "Octop-device-linux-amd64-" in wf


def test_linux_device_readme_points_at_open_device() -> None:
    readme = (REPO / "desktop/portable/linux-device/README.md").read_text(encoding="utf-8")
    assert "./open-device.sh" in readme
    assert "https://octop.effaf.me" in readme
    # extract example should chmod open-device before invoking it
    extract = readme[readme.find("tar -xzf") : readme.find("tar -xzf") + 500]
    assert "chmod +x open-device.sh" in extract
    assert extract.find("./open-device.sh") > extract.find("chmod +x open-device.sh")
