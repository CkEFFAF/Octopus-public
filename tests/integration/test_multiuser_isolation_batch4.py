"""0038 Batch4 — dual-account AC01–AC14 pin tests (automation-equivalent).

Maps handoff §14 AC01–AC14 / AC-M20…M33 onto automated checks. Does not expand
attack surface beyond known-secure assertions. Live dual-executor hardware
paths that need physical devices remain noted as residual in the Ready report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.auth import TEST_PASSWORD, auth_header, create_user, resolve_user_id

# AC coverage index (automation):
# AC01 invite       → test_ac01_*
# AC02 bind device  → test_ac02_* (browser login ≠ enroll)
# AC03 cross device → test_ac03_* (+ unit devices cross-account)
# AC04 server exec  → Batch1 MCP spawn (re-asserted lightly)
# AC05 content/file → test_ac05_* + Batch1 workspace probes
# AC06 credentials  → Batch1 voice/storage
# AC07 delegated    → test_multiuser_administration.py
# AC08 sessions     → Batch2 JWT revoke
# AC09 long conn    → Batch2 desktop disable
# AC10 mermaid      → frontend sanitize + PublicMarkdown
# AC11 data/bg      → test_ac11_*
# AC12 quota        → test_ac12_*
# AC13 upgrade      → test_ac13_*
# AC14 admin OK     → test_ac14_*


@pytest.fixture
async def dual(env):
    client, server, admin = env
    alice = await create_user(client, admin, username="batch4-alice", permissions=[])
    bob = await create_user(client, admin, username="batch4-bob", permissions=[])
    alice_id = await resolve_user_id(client, admin, "batch4-alice")
    bob_id = await resolve_user_id(client, admin, "batch4-bob")
    return client, server, admin, alice, bob, alice_id, bob_id


@pytest.fixture
async def ordinary(env):
    client, server, admin = env
    auth = await create_user(client, admin, username="batch4-ordinary", permissions=[])
    uid = await resolve_user_id(client, admin, "batch4-ordinary")
    return client, server, admin, auth, uid


async def test_ac01_invite_redeems_once_and_rejects_reuse(env):
    """AC01: single-use invite → ordinary user; reuse rejected."""
    client, _server, admin = env
    created = await client.post(
        "/api/users/invites",
        headers=admin,
        json={"expires_days": 7},
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    assert code

    redeem = await client.post(
        "/api/auth/invite/redeem",
        json={
            "code": code,
            "username": "batch4_invitee",
            "password": "InvitePass12",
        },
    )
    assert redeem.status_code == 200, redeem.text
    body = redeem.json()
    assert body["user"]["role"] == "user"
    assert body["user"]["permissions"] == []

    again = await client.post(
        "/api/auth/invite/redeem",
        json={
            "code": code,
            "username": "batch4_other",
            "password": "InvitePass12",
        },
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVITE_USED"


async def test_ac02_browser_login_does_not_create_executor_device(dual):
    """AC02: password/browser login alone must not mint an executor device."""
    client, _server, _admin, alice, _bob, _aid, _bid = dual
    listed = await client.get("/api/devices", headers=alice)
    assert listed.status_code == 200, listed.text
    assert listed.json().get("devices") == []


async def test_ac03_peer_cannot_list_or_revoke_other_account_device(dual):
    """AC03: A enrolls a device; B cannot list or revoke it."""
    client, _server, _admin, alice, bob, _aid, _bid = dual
    enrolled = await client.post(
        "/api/devices/enroll",
        headers=alice,
        json={
            "name": "alice-laptop",
            "platform": "linux",
            "capabilities": [],
            "permissions": [],
            "roots": [],
        },
    )
    assert enrolled.status_code == 201, enrolled.text
    device_id = enrolled.json()["device"]["device_id"]

    alice_list = await client.get("/api/devices", headers=alice)
    assert alice_list.status_code == 200
    alice_ids = {d["device_id"] for d in alice_list.json()["devices"]}
    assert device_id in alice_ids

    bob_list = await client.get("/api/devices", headers=bob)
    assert bob_list.status_code == 200
    bob_ids = {d["device_id"] for d in bob_list.json().get("devices", [])}
    assert device_id not in bob_ids

    revoke = await client.post(f"/api/devices/{device_id}/revoke", headers=bob)
    assert revoke.status_code in (403, 404), revoke.text
    # Alice still owns it.
    still = await client.get("/api/devices", headers=alice)
    assert device_id in {d["device_id"] for d in still.json()["devices"]}


async def test_ac04_ordinary_mcp_stdio_still_denied(dual, tmp_path):
    """AC04 / AC-M01: ordinary MCP stdio test must not spawn host process."""
    import sys

    client, _server, _admin, alice, _bob, _aid, _bid = dual
    marker = tmp_path / "batch4-mcp-marker.txt"
    source = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text("
        f"'BATCH4', encoding='utf-8')"
    )
    result = await client.post(
        "/api/connectors/custom-mcp/test",
        headers=alice,
        json={
            "server": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-c", source],
            }
        },
    )
    assert not marker.exists()
    assert result.status_code == 403, result.text


async def test_ac05_cannot_point_backend_at_peer_workspace(dual):
    """AC05: A cannot bind local_shell root to B/admin workspace and read it."""
    client, server, _admin, alice, _bob, _aid, _bid = dual
    other_workspace = server.app_runtime.agent_registry.resolve_workspace_dir("main")
    marker = other_workspace / "batch4-private.txt"
    marker.write_text("BATCH4_PEER_PRIVATE", encoding="utf-8")
    result = await client.post(
        "/api/agents",
        headers=alice,
        json={
            "name": "batch4-cross-workspace",
            "config": {
                "backend": {
                    "type": "local_shell",
                    "root_dir": str(other_workspace),
                    "virtual_mode": False,
                }
            },
        },
    )
    if result.status_code in (400, 403):
        return
    assert result.status_code == 201, result.text
    aid = result.json()["agent_id"]
    assert (await client.post(f"/api/agents/{aid}/stop", headers=alice)).status_code == 204
    read = await client.get(
        f"/api/agents/{aid}/workspace/file",
        headers=alice,
        params={"path": str(marker)},
    )
    assert read.status_code in (400, 403, 404), read.text
    assert "BATCH4_PEER_PRIVATE" not in read.text


async def test_ac11_agents_and_private_knowledge_isolated(dual):
    """AC11: peer cannot list private agents/KB owned by the other account."""
    client, server, _admin, alice, bob, alice_id, bob_id = dual
    alice_agent = await client.post(
        "/api/agents",
        headers=alice,
        json={"name": "alice-only-bot", "config": {}},
    )
    # Creating may require providers; fall back to repo-seeded KB isolation.
    if alice_agent.status_code == 201:
        alice_aid = alice_agent.json()["agent_id"]
        bob_agents = await client.get("/api/agents", headers=bob)
        assert bob_agents.status_code == 200
        bob_ids = {a["agent_id"] for a in bob_agents.json()}
        assert alice_aid not in bob_ids

    kb = server.services.knowledge_repo.create_base(
        owner_user_id=alice_id,
        name="alice-private-kb",
        shared=False,
    )
    bob_list = await client.get("/api/knowledge-bases", headers=bob)
    assert bob_list.status_code == 200, bob_list.text
    bob_kb_ids = {row.get("knowledge_base_id") or row.get("id") for row in bob_list.json()}
    assert kb.id not in bob_kb_ids

    direct = await client.get(f"/api/knowledge-bases/{kb.id}", headers=bob)
    assert direct.status_code in (403, 404), direct.text

    # Owner still sees it.
    alice_list = await client.get("/api/knowledge-bases", headers=alice)
    assert alice_list.status_code == 200
    assert kb.id in {row.get("knowledge_base_id") or row.get("id") for row in alice_list.json()}


async def test_ac12_max_agents_quota_is_per_account(dual):
    """AC12: exhausting A's max_agents must not block B from creating agents."""
    client, _server, admin, alice, bob, alice_id, _bob_id = dual
    capped = await client.patch(
        f"/api/users/{alice_id}",
        headers=admin,
        json={"max_agents": 0},
    )
    assert capped.status_code == 200, capped.text

    alice_create = await client.post(
        "/api/agents",
        headers=alice,
        json={"name": "alice-blocked", "config": {}},
    )
    assert alice_create.status_code in (403, 400), alice_create.text

    bob_create = await client.post(
        "/api/agents",
        headers=bob,
        json={"name": "bob-ok", "config": {}},
    )
    # Bob may still need providers; accept 201 or a non-quota validation error,
    # but must not be blocked by Alice's quota.
    if bob_create.status_code >= 400:
        err = bob_create.json().get("error", {})
        assert "quota" not in str(err).lower()
        assert err.get("code") != "QUOTA_EXCEEDED"
    else:
        assert bob_create.status_code == 201


async def test_ac13_migration_034_ships_sqlite_and_postgres():
    """AC13: browser_sessions + auth_version migration present for both backends."""
    root = Path(__file__).resolve().parents[2]
    mig = root / "src" / "octop" / "infra" / "db" / "migrations"
    sqlite = (mig / "034_browser_sessions_auth_version.sql").read_text(encoding="utf-8")
    pg = (mig / "034_browser_sessions_auth_version.pg.sql").read_text(encoding="utf-8")
    for body in (sqlite, pg):
        assert "auth_version" in body
        assert "browser_sessions" in body


async def test_ac14_admin_host_directory_ops_still_work(env, tmp_path):
    """AC14: administrator can still manage control-server directories."""
    client, _server, admin = env
    host_data = tmp_path / "admin-host"
    host_data.mkdir()
    listed = await client.get(
        "/api/filesystem/dirs",
        headers=admin,
        params={"path": str(host_data)},
    )
    assert listed.status_code == 200, listed.text
    created = await client.post(
        "/api/filesystem/mkdir",
        headers=admin,
        json={"path": str(host_data), "base_name": "admin-ok"},
    )
    assert created.status_code == 200, created.text
    assert (host_data / "admin-ok").is_dir()


async def test_ac08_replay_after_logout_still_denied(dual):
    """AC08 smoke: logout invalidates the presented browser JWT."""
    client, _server, _admin, alice, _bob, _aid, _bid = dual
    assert (await client.post("/api/auth/logout", headers=alice)).status_code == 204
    replay = await client.get("/api/auth/me", headers=alice)
    assert replay.status_code in (401, 403)
    # Fresh login works.
    fresh = await auth_header(client, username="batch4-alice", password=TEST_PASSWORD)
    me = await client.get("/api/auth/me", headers=fresh)
    assert me.status_code == 200
    assert me.json()["username"] == "batch4-alice"


async def test_ac05_download_and_doc_jail_peer_and_ssh(dual, tmp_path):
    """AC05 review: download/read_doc reject peer agents path and ~/.ssh."""
    client, server, _admin, alice, _bob, _aid, _bid = dual
    created = await client.post(
        "/api/agents",
        headers=alice,
        json={"name": "batch4-jail-agent", "config": {}},
    )
    assert created.status_code == 201, created.text
    aid = created.json()["agent_id"]
    assert (await client.post(f"/api/agents/{aid}/stop", headers=alice)).status_code == 204

    peer_ws = server.app_runtime.agent_registry.resolve_workspace_dir("main")
    peer_marker = peer_ws / "batch4-peer-secret.txt"
    peer_marker.write_text("PEER_SECRET", encoding="utf-8")
    peer_doc = peer_ws / "batch4-peer.docx"
    peer_doc.write_bytes(b"PK\x03\x04not-a-real-docx")

    ssh_key = tmp_path / "home" / "bob" / ".ssh" / "id_rsa"
    ssh_key.parent.mkdir(parents=True)
    ssh_key.write_text("SSH_PRIVATE", encoding="utf-8")

    for endpoint, path in (
        ("download", str(peer_marker)),
        ("file", str(peer_marker)),
        ("doc", str(peer_doc)),
        ("download", str(ssh_key)),
        ("file", str(ssh_key)),
        ("download", "/home/bob/.ssh/id_rsa"),
    ):
        result = await client.get(
            f"/api/agents/{aid}/workspace/{endpoint}",
            headers=alice,
            params={"path": path},
        )
        assert result.status_code in (400, 403, 404), (
            f"{endpoint} {path}: {result.status_code}; {result.text}"
        )
        assert "PEER_SECRET" not in result.text
        assert "SSH_PRIVATE" not in result.text


async def test_ac04_put_custom_mcp_stdio_not_persisted(ordinary):
    """F01 review: PUT custom-mcp stdio denied before DB write."""
    from octop.infra.connectors.custom_mcp import CUSTOM_MCP_KIND

    client, server, _, auth, user_id = ordinary
    before = server.services.repos.connector_repo.get_by_user_kind(user_id, CUSTOM_MCP_KIND)
    result = await client.put(
        "/api/connectors/custom-mcp",
        headers=auth,
        json={
            "servers": {
                "evil-stdio": {
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-c", "pass"],
                }
            }
        },
    )
    assert result.status_code in (401, 403), result.text
    after = server.services.repos.connector_repo.get_by_user_kind(user_id, CUSTOM_MCP_KIND)
    assert after is None
    assert before is None
