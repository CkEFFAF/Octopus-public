"""Portable skill paths must be safe on Windows as well as POSIX."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.errors import OctopError
from octop.infra.skills.skill_package_store import SkillPackageStore
from octop.infra.skills.skill_packages import (
    SkillPackageError,
    normalize_skill_files,
    read_skill_directory,
    validate_skill_slug,
)


@pytest.mark.parametrize(
    "slug", ["C:payload", "safe:stream", "CON", "nul.txt", "demo.", "LPT1", "bad\nname"]
)
def test_rejects_windows_special_skill_names(slug: str) -> None:
    with pytest.raises(SkillPackageError):
        validate_skill_slug(slug)


@pytest.mark.parametrize(
    "path",
    [
        "D:escape.py",
        "docs/readme:secret",
        "docs/NUL.txt",
        "docs/.. /evil",
        "docs/file.",
        "docs/file ",
        "bad\nname.py",
    ],
)
def test_rejects_windows_special_package_paths(path: str) -> None:
    with pytest.raises(SkillPackageError):
        normalize_skill_files([("SKILL.md", b"safe"), (path, b"payload")])


def test_rejects_case_aliases_and_file_directory_collisions() -> None:
    for paths in (("SKILL.md", "skill.md"), ("scripts", "scripts/run.py"), ("assets/", "assets")):
        with pytest.raises(SkillPackageError):
            normalize_skill_files([(path, b"content") for path in paths])


def test_preserves_portable_unicode_paths_and_directory_markers() -> None:
    assert validate_skill_slug("中文技能") == "中文技能"
    assert (
        normalize_skill_files([("SKILL.md", b"safe"), ("资料/", b""), ("资料/说明.md", b"ok")])[-1][
            0
        ]
        == "资料/说明.md"
    )


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink privilege unavailable")


def test_package_root_symlink_is_not_read(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("safe")
    linked = tmp_path / "linked"
    _directory_link(linked, outside)
    with pytest.raises(SkillPackageError, match="linked"):
        read_skill_directory(linked)


def test_linked_install_destination_cannot_overwrite_other_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest = outside / "SKILL.md"
    manifest.write_bytes(b"original")
    root = tmp_path / "packages"
    parent = root / "package" / "skills"
    parent.mkdir(parents=True)
    _directory_link(parent / "demo", outside)
    store = SkillPackageStore(repo=SimpleNamespace(), root=root)
    with pytest.raises(OctopError, match="linked"):
        store.write_skill("package", "demo", [("SKILL.md", b"overwritten")])
    assert manifest.read_bytes() == b"original"
