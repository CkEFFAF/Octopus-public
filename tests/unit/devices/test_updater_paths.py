"""Update metadata must not select directories outside the staging area."""

from pathlib import Path

import pytest

from octop.infra.devices.update_policy import parse_policy
from octop.infra.devices.updater import stage_side_by_side


@pytest.mark.parametrize(
    "version", ["", ".", "..", "../victim", "..\\victim", "/victim", "C:\\victim", "C:victim"]
)
def test_stage_rejects_unsafe_version_before_touching_files(tmp_path: Path, version: str) -> None:
    current = tmp_path / "current"
    current.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    archive = tmp_path / "package.bin"
    archive.write_bytes(b"new")

    with pytest.raises(ValueError, match="version"):
        stage_side_by_side(archive, current_dir=current, version=version)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "releases").exists()


@pytest.mark.parametrize("version", ["../victim", "..\\victim", "/victim", "C:victim"])
def test_policy_rejects_path_versions(version: str) -> None:
    with pytest.raises(ValueError, match="target_version"):
        parse_policy({"target_version": version})


@pytest.mark.parametrize("link_releases", [True, False])
def test_stage_does_not_follow_staging_directory_links(tmp_path: Path, link_releases: bool) -> None:
    install_root = tmp_path / "install"
    install_root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    releases = install_root / "releases"
    if link_releases:
        link = releases
    else:
        releases.mkdir()
        link = releases / "1.2.3"
    try:
        link.symlink_to(victim, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    archive = tmp_path / "package.bin"
    archive.write_bytes(b"new")

    with pytest.raises(ValueError, match="version"):
        stage_side_by_side(archive, current_dir=install_root / "current", version="1.2.3")

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_stage_rejects_absolute_version(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    archive = tmp_path / "package.bin"
    archive.write_bytes(b"new")

    with pytest.raises(ValueError, match="version"):
        stage_side_by_side(archive, current_dir=tmp_path / "current", version=str(victim))

    assert sentinel.read_text(encoding="utf-8") == "keep"
