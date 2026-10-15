from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from octop.infra.devices import capabilities
from octop.infra.errors import OctopError
from octop.infra.execution.skills import ExecutionSkillService
from octop.infra.skills.external_sources import load_external_skill


def skill(home: Path) -> Path:
    directory = home / ".codex" / "skills" / "review"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: Review\ndescription: Check code\n---\nBody\n", encoding="utf-8"
    )
    (directory / "guide.txt").write_bytes(b"guide")
    return directory


def test_catalog_keeps_credentials_on_device_and_does_not_claim_cli_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill(tmp_path)
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.local]\ncommand="mcp-command"\nargs=["--secret", "hidden"]\n'
        '[mcp_servers.local.env]\nTOKEN="secret-token"\n'
        '[mcp_servers.remote]\nurl="https://secret-endpoint/?key=hidden"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        capabilities.shutil, "which", lambda name: "/bin/codex" if name == "codex" else None
    )
    catalog = capabilities.discover(tmp_path)
    serialized = json.dumps(catalog)
    for private in ("hidden", "secret-token", "secret-endpoint", "TOKEN"):
        assert private not in serialized
    entries = {entry["id"]: entry for entry in catalog["entries"]}
    assert entries["cli:codex"]["status"] == "installed"
    assert entries["cli:codex"]["version"] is None
    assert "not probed" in entries["cli:codex"]["reason"]
    assert entries["mcp:codex:local"]["dependency_available"] is False
    assert entries["mcp:codex:remote"]["status"] == "configured"
    assert "manifest" not in entries["skill:codex:review"]


def test_inspection_rejects_changed_source_and_invalid_mcp_is_visible(tmp_path: Path) -> None:
    directory = skill(tmp_path)
    _, digest = load_external_skill(tmp_path, "codex", "review")
    inspected = capabilities.inspect_skill("codex", "review", digest, tmp_path)
    assert inspected["files"] == ["SKILL.md", "guide.txt"]
    (directory / "guide.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        capabilities.inspect_skill("codex", "review", digest, tmp_path)
    (tmp_path / ".claude.json").write_text("invalid secret value", encoding="utf-8")
    invalid = next(
        entry
        for entry in capabilities.discover(tmp_path)["entries"]
        if entry["id"] == "configuration:claude"
    )
    assert invalid["status"] == "unavailable"
    assert invalid["reason"] == "JSONDecodeError"


async def test_remote_package_reads_the_frozen_context_and_rechecks_digest(tmp_path: Path) -> None:
    directory = skill(tmp_path)
    _, digest = load_external_skill(tmp_path, "codex", "review")
    inspected = capabilities.inspect_skill("codex", "review", digest, tmp_path)
    calls = []

    async def call(owner: int, context: str, action: str, params: dict[str, Any]) -> Any:
        calls.append((owner, context, action))
        if action == "capabilities.skill.inspect":
            result = inspected
        else:
            data = Path(params["path"]).read_bytes()[params["offset"] :][: params["length"]]
            result = {"data_b64": base64.b64encode(data).decode(), "eof": True}
        return {"context": {"device_id": "original-device"}, "result": result}

    service = ExecutionSkillService(
        SimpleNamespace(get=lambda owner, context: SimpleNamespace(agent_id="expert"), call=call)
    )
    package = await service.package(1, "frozen-context", "expert", "codex", "review", digest)
    assert dict(package.files)["guide.txt"] == b"guide"
    assert all(owner == 1 and context == "frozen-context" for owner, context, _ in calls)
    (directory / "guide.txt").write_bytes(b"changed after inspection")
    with pytest.raises(OctopError, match="changed"):
        await service.package(1, "frozen-context", "expert", "codex", "review", digest)
    with pytest.raises(OctopError, match="another expert"):
        await service.package(1, "frozen-context", "other", "codex", "review", digest)
    inspected["files"] = [123]
    with pytest.raises(OctopError, match="invalid skill snapshot"):
        await service.package(1, "frozen-context", "expert", "codex", "review", digest)
