"""0045 integration: agent-access-keys HTTP + real ACP stdio client (not curl)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.support.auth import create_agent

ALL_SCOPES = [
    "experts.read",
    "tasks.create",
    "tasks.read",
    "tasks.input",
    "tasks.cancel",
    "resources.read",
]


@pytest.mark.asyncio
async def test_agent_access_key_http_lifecycle_and_key_login_rejected(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, srv, auth = env_with_provider
    agent_id = await create_agent(client, auth)

    r = await client.post(
        "/api/auth/agent-access-keys",
        headers=auth,
        json={
            "name": "laptop-zed",
            "days": 30,
            "scopes": ALL_SCOPES,
            "expert_ids": [agent_id],
            "allow_existing_threads": False,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    secret = body["secret"]
    assert secret.startswith("oaa_")
    assert "secret" not in json.dumps(body["key"])
    assert body["acp_launch"]["command"] == "octop"
    assert body["acp_launch"]["protocol"]["package_version"] == "0.11.0"
    key_id = body["key"]["key_id"]

    listed = await client.get("/api/auth/agent-access-keys", headers=auth)
    assert listed.status_code == 200
    assert all("secret" not in k for k in listed.json()["keys"])

    bad = await client.post("/api/auth/key-login", json={"access_key": secret})
    assert bad.status_code == 401

    experts = await client.get("/api/auth/agent-access-keys/experts", headers=auth)
    assert experts.status_code == 200
    assert any(e["expert_id"] == agent_id for e in experts.json())

    mint = await client.post(
        "/api/auth/agent-access-keys",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "name": "evil",
            "days": 7,
            "scopes": ["tasks.read"],
            "expert_ids": [agent_id],
        },
    )
    assert mint.status_code == 403

    from octop.infra.auth.access_keys import AccessKeyService

    me = (await client.get("/api/auth/me", headers=auth)).json()
    oak = AccessKeyService(srv.services.repos).create(
        int(me["id"]), "browser", 30, True, True
    )["secret"]
    oak_bearer = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {oak}"},
    )
    assert oak_bearer.status_code == 401

    # Machine bearer reaches work-items (empty list ok) when not revoked
    ok_list = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert ok_list.status_code == 200

    # Missing scope: create a read-only key and try cancel path later via revoke test
    rev = await client.post(f"/api/auth/agent-access-keys/{key_id}/revoke", headers=auth)
    assert rev.status_code == 204
    after = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert after.status_code == 401



@pytest.mark.asyncio
async def test_ac_0045_01_real_acp_client_stdio_not_curl(tmp_path: Path) -> None:
    """AC-0045-01 evidence: official agent-client-protocol ClientSideConnection.

    Spawns the remote ACP adapter as a stdio subprocess and drives it with
    ``acp.spawn_agent_process`` (JSON-RPC). This is **not** curl-to-Octop-HTTP.
    """
    from acp import spawn_agent_process
    from acp.schema import (
        ClientCapabilities,
        Implementation,
        InitializeResponse,
        PromptResponse,
        TextContentBlock,
    )

    class DummyClient:
        async def session_update(self, **kwargs: Any) -> None:
            return None

        async def request_permission(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def read_text_file(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def write_text_file(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def create_terminal(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def terminal_output(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def release_terminal(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def wait_for_terminal_exit(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def kill_terminal(self, **kwargs: Any) -> Any:
            raise NotImplementedError

        async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            return {}

        async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
            return None

    helper = Path(__file__).resolve().parent / "_helpers" / "acp_remote_stub_agent.py"
    py = str(Path(__file__).resolve().parents[1].parent / ".venv" / "bin" / "python")
    if not Path(py).exists():
        import sys

        py = sys.executable

    async with spawn_agent_process(
        DummyClient(),
        py,
        str(helper),
        use_unstable_protocol=True,
    ) as (conn, _proc):
        init = await asyncio.wait_for(
            conn.initialize(
                protocol_version=1,
                client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="octop-test-acp-client", version="0.0.1"),
            ),
            timeout=10,
        )
        assert isinstance(init, InitializeResponse)
        assert init.agent_info is not None
        assert init.agent_info.name == "octop-acp-remote"
        assert init.agent_capabilities is not None
        assert init.agent_capabilities.load_session is True

        sess = await asyncio.wait_for(conn.new_session(cwd=str(tmp_path)), timeout=10)
        assert sess.session_id

        resp = await asyncio.wait_for(
            conn.prompt(
                session_id=sess.session_id,
                prompt=[TextContentBlock(type="text", text="请总结一下进度")],
            ),
            timeout=15,
        )
        assert isinstance(resp, PromptResponse)
        assert resp.stop_reason in {"end_turn", "cancelled", "max_tokens"}

        loaded = await asyncio.wait_for(
            conn.load_session(cwd=str(tmp_path), session_id=sess.session_id),
            timeout=10,
        )
        assert loaded is not None


@pytest.mark.asyncio
async def test_scope_missing_forbids_create(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, _srv, auth = env_with_provider
    agent_id = await create_agent(client, auth)
    r = await client.post(
        "/api/auth/agent-access-keys",
        headers=auth,
        json={
            "name": "ro",
            "days": 7,
            "scopes": ["tasks.read"],
            "expert_ids": [agent_id],
        },
    )
    assert r.status_code == 201
    secret = r.json()["secret"]
    # Need an origin thread first — create via human, then machine without tasks.create
    thr = await client.post(f"/api/agents/{agent_id}/threads", headers=auth)
    assert thr.status_code == 201
    tid = thr.json()["thread_id"]
    denied = await client.post(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "command_id": "cmd-deny-1",
            "agent_id": agent_id,
            "origin_thread_id": tid,
            "title": "nope",
            "instructions": "x",
            "schema_version": 1,
        },
    )
    assert denied.status_code == 403
