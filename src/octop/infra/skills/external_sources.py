"""Discover skills installed by local coding assistants before importing them."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from octop.infra.skills.skill_packages import (
    ResolvedSkillPackage,
    SkillPackageError,
    resolve_skill_package,
    validate_skill_slug,
)
from octop.infra.utils.frontmatter import parse_frontmatter

SOURCE_DIRS = {
    "codex": (".codex", "skills"),
    "claude": (".claude", "skills"),
    "opencode": (".config", "opencode", "skills"),
    "opencode_local": (".opencode", "skills"),
}
MAX_SKILLS = 200
MAX_FILES = 128
MAX_ENTRIES = 1024
MAX_BYTES = 8 * 1024 * 1024


def _skill_dir(home: Path, source: str, slug: str) -> Path:
    if source not in SOURCE_DIRS:
        raise ValueError("unknown external source")
    try:
        validate_skill_slug(slug)
    except SkillPackageError as exc:
        raise ValueError("invalid skill name") from exc
    root = home
    for part in SOURCE_DIRS[source]:
        root = root / part
        if root.is_symlink():
            raise ValueError("external source contains a link")
    skill_dir = root / slug
    if root.is_symlink() or skill_dir.is_symlink() or not skill_dir.is_dir():
        raise ValueError("external skill is unavailable")
    return skill_dir


def load_external_skill(home: Path, source: str, slug: str) -> tuple[ResolvedSkillPackage, str]:
    """Read a bounded, symlink-free snapshot and return its content digest."""
    skill_dir = _skill_dir(home, source, slug)
    files: list[tuple[str, bytes]] = []
    total = 0
    entries = 0
    for current, directories, filenames in os.walk(skill_dir, followlinks=False):
        directories.sort()
        for name in [*directories, *sorted(filenames)]:
            entries += 1
            if entries > MAX_ENTRIES:
                raise ValueError("external skill has too many entries")
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError("external skill contains a link")
            if not path.is_file():
                continue
            if len(files) >= MAX_FILES:
                raise ValueError("external skill has too many files")
            size = path.stat().st_size
            if size > MAX_BYTES - total:
                raise ValueError("external skill is too large")
            data = path.read_bytes()
            total += len(data)
            if total > MAX_BYTES:
                raise ValueError("external skill is too large")
            files.append((path.relative_to(skill_dir).as_posix(), data))
    files.sort(key=lambda item: item[0])
    try:
        package = resolve_skill_package(slug=slug, files=files, source=source)
    except SkillPackageError as exc:
        raise ValueError(str(exc)) from exc
    return package, external_package_digest(package)


def external_package_digest(package: ResolvedSkillPackage) -> str:
    """Hash the canonical file names and bytes shared by all source adapters."""
    digest = hashlib.sha256()
    for name, data in package.files:
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def discover_external_skills(home: Path) -> list[dict[str, Any]]:
    """List only valid candidates; discovery never installs or enables them."""
    found: list[dict[str, Any]] = []
    for source, parts in SOURCE_DIRS.items():
        root = home.joinpath(*parts)
        if not root.is_dir() or root.is_symlink():
            continue
        for skill_dir in sorted(root.iterdir()):
            if len(found) >= MAX_SKILLS:
                return found
            if not skill_dir.is_dir() or skill_dir.is_symlink():
                continue
            try:
                package, digest = load_external_skill(home, source, skill_dir.name)
                manifest = next(data for name, data in package.files if name == "SKILL.md")
                raw = manifest.decode("utf-8")
                meta, _ = parse_frontmatter(raw)
            except (ValueError, OSError, UnicodeError, StopIteration):
                continue
            found.append(
                {
                    "source": source,
                    "slug": skill_dir.name,
                    "name": str(meta.get("name") or skill_dir.name),
                    "description": str(meta.get("description") or ""),
                    "digest": digest,
                    "manifest": raw[:32_768],
                    "files": [name for name, _ in package.files],
                    "file_count": len(package.files),
                }
            )
    return found
