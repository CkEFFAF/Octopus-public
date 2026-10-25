"""0038 Batch1 isolation probes (F01–F05).

Adapted from the multiuser handoff audit probes; assertions describe secure
behavior after the Batch1 fixes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.support.auth import create_user, resolve_user_id


@pytest.fixture
async def ordinary(env):
    client, server, admin = env
    auth = await create_user(client, admin, username="audit-user", permissions=[])
    uid = await resolve_user_id(client, admin, "audit-user")
    return client, server, admin, auth, uid


@pytest.mark.parametrize("operation", ["dirs", "mkdir", "rename"])
async def test_ordinary_user_cannot_manage_host_directories(ordinary, tmp_path, operation):
    client, _, _, auth, _ = ordinary
    host_data = tmp_path / "host-data"
    host_data.mkdir()
    (host_data / "another-users-project").mkdir()
    if operation == "dirs":
        result = await client.get(
            "/api/filesystem/dirs", headers=auth, params={"path": str(host_data)}
        )
    elif operation == "mkdir":
        result = await client.post(
            "/api/filesystem/mkdir",
            headers=auth,
            json={"path": str(host_data), "base_name": "created-by-unprivileged-user"},
        )
    else:
        result = await client.post(
            "/api/filesystem/rename",
            headers=auth,
            json={
                "path": str(host_data / "another-users-project"),
                "new_name": "renamed-by-unprivileged-user",
            },
        )
    assert result.status_code == 403, (
        f"Unprivileged host {operation}: HTTP {result.status_code}; {result.text}"
    )


async def test_voice_provider_list_does_not_return_secret_to_ordinary_user(ordinary):
    client, server, _, auth, _ = ordinary
    secret = "AUDIT_SYNTHETIC_VOICE_SECRET"
    server.services.voice_provider_repo.create(
        name="audit-voice",
        kind="openai",
        capability="tts",
        base_url="https://example.invalid",
        api_key=secret,
        extra_json=json.dumps({"secret_id": "SID", "secret_key": secret}),
    )
    result = await client.get("/api/voice/providers", headers=auth)
    assert result.status_code == 200, result.text
    assert secret not in result.text
    assert "SID" not in result.text
    body = result.json()
    row = next(r for r in body if r["name"] == "audit-voice")
    assert "api_key" not in row or row.get("api_key") in (None, "")
    assert row.get("has_api_key") is True
    assert "secret_key" not in (row.get("extra") or {})


async def test_storage_list_does_not_return_config_secret_to_ordinary_user(ordinary):
    client, server, _, auth, _ = ordinary
    secret = "AUDIT_SYNTHETIC_STORAGE_SECRET"
    server.services.storage_backend_repo.create(
        name="audit-storage",
        kind="opensandbox",
        endpoint="sandbox.example.invalid",
        config_json=json.dumps({"api_key": secret, "sandbox_scope": "agent"}),
        secret_key=secret,
    )
    result = await client.get("/api/storage-backends", headers=auth)
    assert result.status_code == 200, result.text
    assert secret not in result.text
    row = next(r for r in result.json() if r["name"] == "audit-storage")
    assert row.get("has_secret_key") is True
    assert row.get("has_config_secret") is True
    cfg = json.loads(row["config_json"] or "{}")
    assert "api_key" not in cfg
    assert cfg.get("sandbox_scope") == "agent"


async def test_user_agent_cannot_read_control_server_file(ordinary, tmp_path):
    client, server, _, auth, _ = ordinary
    target = tmp_path / "control-server-data"
    target.mkdir()
    marker = target / "private.txt"
    marker.write_text("AUDIT_SYNTHETIC_HOST_DATA", encoding="utf-8")
    result = await client.post(
        "/api/agents",
        headers=auth,
        json={
            "name": "audit-owned",
            "config": {
                "backend": {
                    "type": "local_shell",
                    "root_dir": str(target),
                    "virtual_mode": False,
                }
            },
        },
    )
    if result.status_code in (400, 403):
        return
    assert result.status_code == 201, result.text
    aid = result.json()["agent_id"]
    stopped = await client.post(f"/api/agents/{aid}/stop", headers=auth)
    assert stopped.status_code == 204, stopped.text
    result = await client.get(
        f"/api/agents/{aid}/workspace/file",
        headers=auth,
        params={"path": str(marker)},
    )
    assert result.status_code in (400, 403, 404), (
        f"Control host data read through owned agent: {result.status_code}; {result.text}"
    )


async def test_ordinary_user_cannot_spawn_control_server_process_via_mcp(ordinary, tmp_path):
    client, _, _, auth, _ = ordinary
    marker = tmp_path / "audit-process-marker.txt"
    source = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text("
        f"'AUDIT_SAFE_PROCESS_MARKER', encoding='utf-8')"
    )
    result = await client.post(
        "/api/connectors/custom-mcp/test",
        headers=auth,
        json={
            "server": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-c", source],
            }
        },
    )
    assert not marker.exists(), (
        f"Unprivileged user executed a process on the control host: "
        f"HTTP {result.status_code}; {result.text}"
    )
    assert result.status_code == 403, result.text


async def test_storage_patch_preserves_config_secret_when_public_fields_update(ordinary):
    """Redacted config_json round-trip must not wipe nested secrets (F05)."""
    client, server, admin, _, _ = ordinary
    secret = "AUDIT_KEEP_STORAGE_SECRET"
    bid = server.services.storage_backend_repo.create(
        name="audit-merge-storage",
        kind="opensandbox",
        endpoint="sandbox.example.invalid",
        config_json=json.dumps({"api_key": secret, "sandbox_scope": "agent"}),
    )
    result = await client.patch(
        f"/api/admin/storage-backends/{bid}",
        headers=admin,
        json={"config_json": json.dumps({"sandbox_scope": "user", "username": "bob"})},
    )
    assert result.status_code == 200, result.text
    assert secret not in result.text
    stored = server.services.storage_backend_repo.get(bid)
    assert stored is not None
    cfg = json.loads(stored.config_json or "{}")
    assert cfg["api_key"] == secret
    assert cfg["sandbox_scope"] == "user"
    assert cfg["username"] == "bob"
