"""tests/unit/test_release_download_links.py"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_download_links.py"


def _load():
    spec = importlib.util.spec_from_file_location("release_download_links", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_tag_accepts_with_or_without_v() -> None:
    mod = _load()
    assert mod.split_tag("0.9.31") == ("v0.9.31", "0.9.31")
    assert mod.split_tag("v0.9.31") == ("v0.9.31", "0.9.31")


def test_render_download_section_matches_github_asset_names(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    mod = _load()
    body = mod.render_download_section("0.9.31")
    base = "https://github.com/TencentCloud/Octop/releases/download/v0.9.31"
    assert f"{base}/Octop-desktop-windows-amd64-0.9.31.exe" in body
    assert f"{base}/Octop-desktop-windows-arm64-0.9.31.exe" in body
    assert f"{base}/Octop-portable-windows-amd64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-windows-arm64-0.9.31.zip" in body
    assert f"{base}/Octop-desktop-darwin-arm64-0.9.31.dmg" in body
    assert f"{base}/Octop-desktop-darwin-amd64-0.9.31.dmg" in body
    assert f"{base}/Octop-portable-darwin-arm64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-darwin-amd64-0.9.31.zip" in body
    assert f"{base}/Octop-desktop-linux-amd64-0.9.31.tar.gz" in body
    assert f"{base}/Octop-desktop-linux-arm64-0.9.31.tar.gz" in body
    assert f"{base}/Octop-portable-linux-amd64-0.9.31.zip" in body
    assert f"{base}/Octop-portable-linux-arm64-0.9.31.zip" in body
    assert f"{base}/Octop-fnos-docker-0.9.31.fpk" in body
    assert f"{base}/Octop-fnos-native-0.9.31.fpk" in body
    assert f"{base}/Octop-fnos-native-arm64-0.9.31.fpk" in body
    assert "Docker (recommended; x86 and ARM)" in body
    assert "Native x86_64" in body
    assert "Native ARM64 (no Docker)" in body
    assert "pip install" not in body
    assert "## Downloads" in body


def test_private_fork_downloads_use_own_repository_and_available_packages(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "CkEFFAF/Octopus")
    monkeypatch.delenv("OCTOP_RELEASE_PLATFORMS", raising=False)
    body = _load().render_download_section("1.0.2b7")
    base = "https://github.com/CkEFFAF/Octopus/releases/download/v1.0.2b7"
    assert f"{base}/Octop-portable-windows-amd64-1.0.2b7.zip" in body
    assert f"{base}/Octop-portable-linux-amd64-1.0.2b7.zip" in body
    assert f"{base}/Octop-device-linux-amd64-1.0.2b7.tar.gz" in body
    assert "TencentCloud/Octop" not in body
    assert "darwin" not in body


def test_fork_downloads_include_configured_macos_architectures(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "CkEFFAF/Octopus-public")
    monkeypatch.setenv("OCTOP_RELEASE_PLATFORMS", "windows-amd64, darwin-arm64, darwin-amd64")
    body = _load().render_download_section("1.0.2b22")
    base = "https://github.com/CkEFFAF/Octopus-public/releases/download/v1.0.2b22"
    for arch in ("arm64", "amd64"):
        assert f"{base}/Octop-portable-darwin-{arch}-1.0.2b22.zip" in body
        assert f"{base}/Octop-desktop-darwin-{arch}-1.0.2b22.dmg" in body
    assert "Portable / device client" in body
    assert "TencentCloud/Octop" not in body


def test_fork_downloads_omit_unselected_macos_architecture(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "CkEFFAF/Octopus-public")
    monkeypatch.setenv("OCTOP_RELEASE_PLATFORMS", "darwin-arm64")
    body = _load().render_download_section("1.0.2b22")
    assert "Octop-portable-darwin-arm64-1.0.2b22.zip" in body
    assert "darwin-amd64" not in body
