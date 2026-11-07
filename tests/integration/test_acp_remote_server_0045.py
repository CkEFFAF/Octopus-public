"""Official ACP stdio client → production CLI → real Octop HTTP app.

Only the LLM worker is deterministic; auth, session grants, work items, history,
permission dispatch and the adapter run their production implementations.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from acp import spawn_agent_process
from acp.schema import AllowedOutcome, RequestPermissionResponse, TextContentBlock

from tests.support.auth import create_agent


class AcpClient:
    def __init__(self, decision: str = "reject") -> None:
        self.updates: list[dict[str, Any]] = []
        self.permissions: list[dict[str, Any]] = []
        self.decision = decision
        self.text_received = asyncio.Event()

    async def session_update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)
        if kwargs["update"].session_update == "agent_message_chunk":
            self.text_received.set()

    async def request_permission(self, **kwargs: Any) -> Any:
        self.permissions.append(kwargs)
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=self.decision)
        )


@asynccontextmanager
async def acp_connection(
    client: Any, human: dict[str, str], expert: str, tmp_path: Path, peer: AcpClient
):
    minted = await client.post(
        "/api/auth/agent-access-keys",
        headers=human,
        json={
            "name": "official-client",
            "days": 1,
            "expert_ids": [expert],
            "scopes": [
                "experts.read",
                "tasks.create",
                "tasks.read",
                "tasks.input",
                "tasks.cancel",
                "resources.read",
            ],
        },
    )
    assert minted.status_code == 201
    token_file = tmp_path / "credential"
    token_file.write_text(minted.json()["secret"], encoding="utf-8")
    token_file.chmod(0o600)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client._octop_app, log_level="critical", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        child_env = {
            **os.environ,
            "OCTOP_HOME": str(tmp_path / "client-cache"),
            "OCTOP_ACP_TOKEN_FILE": str(token_file),
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        }
        # The secret is in a private file, absent from argv and captured stdout.
        async with spawn_agent_process(
            peer,
            sys.executable,
            "-m",
            "octop",
            "acp-remote",
            "--server",
            f"http://127.0.0.1:{port}",
            "--expert",
            expert,
            env=child_env,
            use_unstable_protocol=True,
        ) as (conn, _):
            initialized = await asyncio.wait_for(conn.initialize(protocol_version=1), 20)
            assert initialized.protocol_version == 1
            assert initialized.agent_capabilities.load_session
            yield conn
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        sock.close()


@pytest.mark.asyncio
async def test_real_server_text_followup_load_and_revocation(env_with_provider, tmp_path):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    worker = server.app_runtime.agent_registry.get_agent(expert)
    answer = "你好，任务完成。" + "完整结果" * 1200
    worker.chunks = [{"type": "token", "content": answer}]
    peer = AcpClient()
    async with acp_connection(client, human, expert, tmp_path, peer) as conn:
        session = await conn.new_session(cwd=str(tmp_path))
        result = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="用中文汇报")],
            ),
            20,
        )
        assert result.stop_reason == "end_turn"
        assert any(getattr(item["update"].content, "text", "") == answer for item in peer.updates)
        peer.updates.clear()
        await conn.load_session(cwd=str(tmp_path), session_id=session.session_id)
        assert [item["update"].session_update for item in peer.updates] == [
            "user_message_chunk",
            "agent_message_chunk",
        ]
        result = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="继续补充")],
            ),
            20,
        )
        assert result.stop_reason == "end_turn"
        # A completed turn starts a new task with context; it cannot feed a terminal worker.
        listed = (await client.get("/api/work-items?status_group=all", headers=human)).json()[
            "items"
        ]
        assert len(listed) == 2
        assert len({item["task_id"] for item in listed}) == 2
        key = (await client.get("/api/auth/agent-access-keys", headers=human)).json()["keys"][0]
        await client.post(f"/api/auth/agent-access-keys/{key['key_id']}/revoke", headers=human)
        from acp import RequestError

        with pytest.raises(RequestError):
            await conn.load_session(cwd=str(tmp_path), session_id=session.session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_real_server_permission_is_decided_by_acp_client(
    env_with_provider, tmp_path, monkeypatch, decision
):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    registry = server.app_runtime.agent_registry
    worker = registry.get_agent(expert)
    worker.chunks = [
        {
            "type": "hitl_required",
            "request": {
                "action_requests": [{"name": "run_command", "args": {"command": "echo approved"}}],
                "review_configs": [
                    {"action_name": "run_command", "allowed_decisions": ["approve", "reject"]}
                ],
            },
        }
    ]
    resumed = []

    async def resume(agent_id, thread_id, decisions):
        resumed.append(decisions)
        yield {
            "type": "token",
            "content": "已批准" if decisions[0]["type"] == "approve" else "已拒绝",
        }

    monkeypatch.setattr(registry, "resume_hitl", resume)
    peer = AcpClient(decision)
    async with acp_connection(client, human, expert, tmp_path, peer) as conn:
        session = await conn.new_session(cwd=str(tmp_path))
        result = await asyncio.wait_for(
            conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="执行前询问")],
            ),
            25,
        )
        assert result.stop_reason == "end_turn"
        assert len(peer.permissions) == 1
        assert peer.permissions[0]["tool_call"].raw_input == {"command": "echo approved"}
        assert resumed == [[{"type": decision}]]
        assert {option.option_id for option in peer.permissions[0]["options"]} == {
            "approve",
            "reject",
        }


@pytest.mark.asyncio
async def test_real_server_cancel_confirms_worker_termination(
    env_with_provider, tmp_path, monkeypatch
):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def slow_worker(agent_id, request):
        started.set()
        try:
            yield {"type": "token", "content": "工作中"}
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(server.app_runtime.agent_registry, "stream", slow_worker)
    async with acp_connection(client, human, expert, tmp_path, AcpClient()) as conn:
        session = await conn.new_session(cwd=str(tmp_path))
        prompt = asyncio.create_task(
            conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="耗时工作")],
            )
        )
        await asyncio.wait_for(started.wait(), 10)
        await conn.cancel(session_id=session.session_id)
        result = await asyncio.wait_for(prompt, 15)
        assert result.stop_reason == "cancelled"
        assert stopped.is_set()
        tasks = (await client.get("/api/work-items?status_group=all", headers=human)).json()[
            "items"
        ]
        assert tasks[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_incremental_output_arrives_before_worker_finishes(
    env_with_provider, tmp_path, monkeypatch
):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    release = asyncio.Event()

    async def streaming_worker(agent_id, request):
        yield {"type": "token", "content": "第一段"}
        await release.wait()
        yield {"type": "token", "content": "第二段"}

    monkeypatch.setattr(server.app_runtime.agent_registry, "stream", streaming_worker)
    peer = AcpClient()
    async with acp_connection(client, human, expert, tmp_path, peer) as conn:
        session = await conn.new_session(cwd=str(tmp_path))
        prompt = asyncio.create_task(
            conn.prompt(
                session_id=session.session_id,
                prompt=[TextContentBlock(type="text", text="分段汇报")],
            )
        )
        try:
            await asyncio.wait_for(peer.text_received.wait(), 10)
            assert not prompt.done()
        finally:
            release.set()
        assert (await asyncio.wait_for(prompt, 15)).stop_reason == "end_turn"
        text = "".join(
            getattr(item["update"].content, "text", "")
            for item in peer.updates
            if item["update"].session_update == "agent_message_chunk"
        )
        assert text == "第一段第二段"
