from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.skills.external_sources import discover_external_skills, load_external_skill


def test_discovery_requires_explicit_import_and_detects_changed_source(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "review"
    skill.mkdir(parents=True)
    manifest = skill / "SKILL.md"
    manifest.write_text("---\nname: Review\ndescription: Check changes\n---\nBody\n")
    (skill / "guide.txt").write_text("guide")

    candidates = discover_external_skills(tmp_path)
    assert len(candidates) == 1
    assert candidates[0]["source"] == "codex"
    assert candidates[0]["file_count"] == 2
    assert candidates[0]["name"] == "Review"
    assert (skill / "SKILL.md").exists()

    package, digest = load_external_skill(tmp_path, "codex", "review")
    assert digest == candidates[0]["digest"]
    assert {name for name, _ in package.files} == {"SKILL.md", "guide.txt"}
    manifest.write_text(manifest.read_text() + "Changed")
    assert load_external_skill(tmp_path, "codex", "review")[1] != digest


def test_discovery_rejects_arbitrary_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid skill name"):
        load_external_skill(tmp_path, "codex", "../private")
    with pytest.raises(ValueError, match="unknown external source"):
        load_external_skill(tmp_path, "other", "review")


def test_digest_distinguishes_file_boundaries_from_embedded_nuls(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "review"
    skill.mkdir(parents=True)
    manifest = b"---\nname: Review\n---\nBody\n"
    (skill / "SKILL.md").write_bytes(manifest)
    (skill / "a.txt").write_bytes(b"abc")
    original = load_external_skill(tmp_path, "codex", "review")[1]
    (skill / "a.txt").unlink()
    (skill / "SKILL.md").write_bytes(manifest + b"\0a.txt\0abc")
    assert load_external_skill(tmp_path, "codex", "review")[1] != original
