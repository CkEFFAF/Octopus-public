"""Real device CLI processes talking to the scoped cloud expert HTTP app."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn

from tests.support.auth import create_agent

SCOPES = ["experts.read", "tasks.create", "tasks.read", "tasks.input", "tasks.cancel"]


@asynccontextmanager
async def http_server(client):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client._octop_app, log_level="critical", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        sock.close()


async def command(state: Path, *args: str):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "octop",
        "device",
        "expert",
        "--state",
        str(state),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "PYTHONUTF8": "1",
        },
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 35)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    raw = stdout if process.returncode == 0 else stderr
    return process.returncode, json.loads(raw), stdout + stderr


async def configure(client, human, expert, state, endpoint):
    response = await client.post(
        "/api/auth/agent-access-keys",
        headers=human,
        json={"name": "device-expert-test", "expert_ids": [expert], "scopes": SCOPES, "days": 1},
    )
    assert response.status_code == 201
    created = response.json()
    created["key_id"] = created["key"]["key_id"]
    token_file = state.parent / f"{state.name}.token"
    token_file.write_text(created["secret"], encoding="utf-8")
    token_file.chmod(0o600)
    code, configured, raw = await command(
        state, "configure", "--server", endpoint, "--token-file", str(token_file)
    )
    assert code == 0, raw
    assert created["secret"].encode() not in raw
    assert configured["credential_id"] == created["key_id"]
    return created


@pytest.mark.asyncio
async def test_device_cli_chinese_followup_recovery_and_revocation(env_with_provider, tmp_path):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    worker = server.app_runtime.agent_registry.get_agent(expert)
    answer = "专家的完整中文回复。" + "方案细节" * 1200
    worker.chunks = [{"type": "token", "content": answer}]
    state = tmp_path / "device-state"
    async with http_server(client) as endpoint:
        key = await configure(client, human, expert, state, endpoint)
        code, listing, _ = await command(state, "list")
        assert code == 0
        assert listing["experts"][0]["expert_id"] == expert
        code, first, raw = await command(
            state, "ask", "--expert", expert, "--message", "你好，请分析", "--command-id", "turn-1"
        )
        assert code == 0, raw
        assert first["status"] == "completed"
        assert first["reply"] == answer
        code, retry, _ = await command(
            state, "ask", "--expert", expert, "--message", "你好，请分析", "--command-id", "turn-1"
        )
        assert code == 0 and retry["task_id"] == first["task_id"]
        code, conflict, _ = await command(
            state, "ask", "--expert", expert, "--message", "改了问题", "--command-id", "turn-1"
        )
        assert code == 1 and conflict["error"] == "command_conflict"
        code, found, _ = await command(state, "find", "--command-id", "turn-1")
        assert code == 0 and found["task"]["task_id"] == first["task_id"]
        worker.chunks = [{"type": "token", "content": "补充说明"}]
        message_file = tmp_path / "question.txt"
        message_file.write_text("请继续补充", encoding="utf-8")
        code, second, raw = await command(
            state,
            "reply",
            "--task",
            first["task_id"],
            "--message-file",
            str(message_file),
            "--command-id",
            "turn-2",
        )
        assert code == 0, raw
        assert second["reply"] == "补充说明"
        assert second["session_id"] == first["session_id"]
        assert second["task_id"] != first["task_id"]
        detail = (await client.get(f"/api/work-items/{second['task_id']}", headers=human)).json()
        assert "你好，请分析" in detail["instructions"]
        assert answer in detail["instructions"]
        assert "请继续补充" in detail["instructions"]
        other = tmp_path / "other-state"
        await configure(client, human, expert, other, endpoint)
        code, forbidden, _ = await command(other, "get", "--task", first["task_id"])
        assert code == 1 and forbidden["http_status"] == 403
        await client.post(f"/api/auth/agent-access-keys/{key['key_id']}/revoke", headers=human)
        code, revoked, raw = await command(state, "get", "--task", first["task_id"])
        assert code == 1 and revoked["error"] == "auth_failed"
        assert key["secret"].encode() not in raw


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_device_cli_permission_requires_explicit_decision(
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
                "action_requests": [{"name": "run_command", "args": {"command": "echo check"}}],
                "review_configs": [
                    {"action_name": "run_command", "allowed_decisions": ["approve", "reject"]}
                ],
            },
        }
    ]
    resumed = []

    async def resume(agent_id, thread_id, decisions):
        resumed.append(decisions)
        yield {"type": "token", "content": "处理完成"}

    monkeypatch.setattr(registry, "resume_hitl", resume)
    state = tmp_path / "state"
    async with http_server(client) as endpoint:
        await configure(client, human, expert, state, endpoint)
        code, pending, raw = await command(
            state, "ask", "--expert", expert, "--message", "操作前询问", "--wait", "10"
        )
        assert code == 0, raw
        assert pending["permission_request"]
        assert not resumed
        code, receipt, raw = await command(
            state,
            "permission",
            "--task",
            pending["task_id"],
            "--attempt",
            pending["current_attempt_id"],
            "--pending",
            pending["permission_request"]["pending_id"],
            "--decision",
            decision,
        )
        assert code == 0, raw
        code, finished, raw = await command(
            state, "wait", "--task", pending["task_id"], "--timeout", "10"
        )
        assert code == 0, raw
        assert finished["status"] == "completed"
        assert resumed == [[{"type": decision}]]


@pytest.mark.asyncio
async def test_device_cli_running_input_and_cancel(env_with_provider, tmp_path, monkeypatch):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    stopped = asyncio.Event()

    async def slow_worker(agent_id, request):
        try:
            yield {"type": "token", "content": "工作中"}
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(server.app_runtime.agent_registry, "stream", slow_worker)
    state = tmp_path / "state"
    async with http_server(client) as endpoint:
        await configure(client, human, expert, state, endpoint)
        code, started, raw = await command(
            state, "ask", "--expert", expert, "--message", "耗时任务", "--wait", "0"
        )
        assert code == 0, raw
        code, supplemented, raw = await command(
            state,
            "reply",
            "--task",
            started["task_id"],
            "--message",
            "补充要求",
            "--command-id",
            "input-1",
            "--wait",
            "0",
        )
        assert code == 0, raw
        assert supplemented["task_id"] == started["task_id"]
        code, cancelled, raw = await command(state, "cancel", "--task", started["task_id"])
        assert code == 0, raw
        code, final, raw = await command(
            state, "wait", "--task", started["task_id"], "--timeout", "10"
        )
        assert code == 0, raw
        assert final["status"] == "cancelled"
        assert stopped.is_set()
        code, recovered, raw = await command(
            state,
            "reply",
            "--task",
            started["task_id"],
            "--message",
            "补充要求",
            "--command-id",
            "input-1",
            "--wait",
            "0",
        )
        assert code == 0, raw
        assert recovered["task_id"] == started["task_id"]
