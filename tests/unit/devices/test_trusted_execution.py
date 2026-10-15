"""Real device I/O through an authenticated owner policy, without directory grants."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from langgraph.config import var_child_runnable_config

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.client import DeviceClient
from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor, save_private_json
from octop.infra.devices.filesystem import NativeFileSystem
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.backend import RequestExecutionBackend
from octop.infra.execution.service import ExecutionService


@pytest.fixture
def fleet(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "hub.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    yield DeviceService(repos), owner, other, tmp_path
    pool.close()


async def attach(
    service: DeviceService, owner: int, directory: Path, *, acknowledge: bool = True
) -> Any:
    directory.mkdir()
    executor = DeviceExecutor(
        [], [], trust_mode="owner", working_dir=str(directory), state_dir=directory / "state"
    )
    enrolled = service.enroll(
        owner_user_id=owner,
        name=directory.name,
        platform="windows" if sys.platform == "win32" else "linux",
        capabilities=executor.capabilities,
        permissions=executor.capabilities,
        roots=[],
        trust_mode="owner",
    )
    device_id = enrolled["device"]["device_id"]
    connection: Any = None
    messages: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        messages.append(frame)
        if frame["type"] in {"hello_ack", "grants"}:
            executor.apply_policy(
                frame["trust_mode"], frame["permissions"], frame.get("working_dir")
            )
            executor.update_grants(frame["grant_version"], frame["permissions"], frame["roots"])
            if connection is not None and acknowledge:
                await report()
        elif frame["type"] == "request":
            value = await executor.execute(
                frame["id"],
                frame["action"],
                frame["params"],
                grant_version=frame["grant_version"],
                permissions=frame["permissions"],
            )
            await service.receive(
                connection, {"type": "result", "id": frame["id"], "ok": True, "result": value}
            )
        elif frame["type"] == "desktop_takeover":
            pytest.fail("owned device was asked to approve its screen")

    async def close() -> None:
        await executor.close()

    connection = await service.connect(
        device_id, enrolled["device_token"], send, close, client_protocol_version=3
    )

    async def report() -> None:
        row = service.owned(owner, device_id)
        await service.receive(
            connection,
            {
                "type": "policy_applied",
                "policy_revision": row.policy_revision,
                "trust_mode": row.trust_mode,
                "runtime": {"working_dir": str(executor.working_dir), "os_user": "test-account"},
            },
        )

    if acknowledge:
        await report()
    return enrolled, executor, connection, messages


async def test_owner_reads_and_writes_outside_default_directory(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    outside = tmp / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    device_id = enrolled["device"]["device_id"]
    content = await service.call(owner, device_id, "fs.read", {"path": str(outside)})
    assert base64.b64decode(content["data_b64"]) == b"original"
    result = await service.call(
        owner,
        device_id,
        "fs.write",
        {"path": "../outside.txt", "data_b64": base64.b64encode(b"updated").decode()},
    )
    assert outside.read_text() == "updated"
    assert result["sha256"]
    assert service.owned(owner, device_id).roots == []
    service.disconnect(connection)
    await executor.close()


async def test_native_transfer_uses_frozen_device_context_and_preserves_binary_outside_cwd(
    fleet: Any,
) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    await service.receive(
        connection,
        {
            "type": "policy_applied",
            "policy_revision": service.owned(
                owner, enrolled["device"]["device_id"]
            ).policy_revision,
            "trust_mode": "owner",
            "runtime": {"transfer_protocol_version": 1},
        },
    )
    executions = ExecutionService(service)
    context = executions.resolve(owner, device_id=enrolled["device"]["device_id"])
    other_context = executions.resolve(owner, device_id=enrolled["device"]["device_id"])
    data = bytes(range(256)) * 8192 + b"verified final bytes"
    digest = hashlib.sha256(data).hexdigest()
    destination = tmp / "binary-outside-default.bin"

    async def call(action: str, params: dict[str, Any]) -> dict[str, Any]:
        return (await executions.call(owner, context.context_id, action, params))["result"]

    try:
        session = await call(
            "fs.upload.begin", {"path": str(destination), "size": len(data), "sha256": digest}
        )
        for offset in range(0, len(data), 1024**2):
            chunk = data[offset : offset + 1024**2]
            receipt = await call(
                "fs.upload.chunk",
                {
                    "transfer_id": session["transfer_id"],
                    "offset": offset,
                    "data_b64": base64.b64encode(chunk).decode(),
                },
            )
            assert receipt["bytes_done"] == offset + len(chunk)
        committed = await call("fs.upload.commit", {"transfer_id": session["transfer_id"]})
        assert committed["sha256"] == digest and destination.read_bytes() == data
        download = await call("fs.download.begin", {"path": str(destination)})
        with pytest.raises(Exception, match="execution context"):
            await executions.call(
                owner,
                other_context.context_id,
                "fs.download.chunk",
                {
                    "transfer_id": download["transfer_id"],
                    "offset": 0,
                },
            )
        collected = bytearray()
        while len(collected) < len(data):
            part = await call(
                "fs.download.chunk",
                {"transfer_id": download["transfer_id"], "offset": len(collected)},
            )
            collected.extend(base64.b64decode(part["data_b64"]))
        await call("fs.download.close", {"transfer_id": download["transfer_id"]})
        assert bytes(collected) == data
        # Content chunks are never copied into operation results or run events.
        journal = (executor.state_dir / "operations.json").read_text()
        assert base64.b64encode(data[:1024]).decode() not in journal
    finally:
        service.disconnect(connection)
        await executor.close()


async def test_owner_desktop_uses_context_without_confirmation_or_input_ledger(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    service, owner, _, tmp = fleet
    monkeypatch.setattr(
        DeviceExecutor, "capabilities", property(lambda self: ["desktop_view", "desktop_control"])
    )
    injector = MagicMock()
    monkeypatch.setattr("octop.infra.devices.desktop.InputInjector", lambda: injector)
    monkeypatch.setattr(
        "octop.infra.desktop.capture.ScreenCapture.capture_jpeg",
        lambda self, **kw: SimpleNamespace(jpeg_b64="private-screen", width=100, height=50),
    )
    service.repos.agent_repo.create(agent_id="desktop-expert", user_id=owner, name="Desktop")
    enrolled, executor, connection, messages = await attach(service, owner, tmp / "desktop")
    executions = ExecutionService(service)
    context = executions.resolve(
        owner,
        device_id=enrolled["device"]["device_id"],
        agent_id="desktop-expert",
        work_mode="computer_use",
    )
    try:
        captured = await executions.call(owner, context.context_id, "desktop.capture", {})
        assert captured["result"]["jpeg_b64"] == "private-screen"
        await executions.call(
            owner, context.context_id, "desktop.input", {"kind": "key", "key": "ctrl+c"}
        )
        await executions.call(
            owner, context.context_id, "desktop.input", {"kind": "type", "text": "private-typing"}
        )
        assert [c.args[0] for c in injector.key_down.call_args_list] == ["Control", "c"]
        injector.type_text.assert_called_once_with("private-typing")
        assert not any(m["type"] == "desktop_takeover" for m in messages)
        operations = service.repos.device_repo.list_operations(owner)
        assert len(operations) == 2
        assert all(op.params["execution_context_id"] == context.context_id for op in operations)
        assert all("key" not in op.params and "text" not in op.params for op in operations)
        plan = executions.resolve(owner, device_id=context.device_id, work_mode="plan")
        with pytest.raises(OctopError, match="only permits observation"):
            await executions.call(
                owner, plan.context_id, "desktop.input", {"kind": "key", "key": "enter"}
            )
    finally:
        service.disconnect(connection)
        await executor.close()


async def test_browser_lane_is_authenticated_and_old_clients_do_not_fall_back(fleet: Any) -> None:
    service, owner, other, tmp = fleet
    for agent in ("expert-a", "expert-b"):
        service.repos.agent_repo.create(agent_id=agent, user_id=owner, name=agent)
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "browser-device")
    executions = ExecutionService(service)
    first = executions.resolve(
        owner, device_id=enrolled["device"]["device_id"], agent_id="expert-a"
    )
    second = executions.resolve(owner, device_id=first.device_id, agent_id="expert-b")
    _, one = executions._prepare(
        owner, first.context_id, "browser.state", {"browser_lane": "forged"}
    )
    _, two = executions._prepare(
        owner, second.context_id, "browser.state", {"browser_lane": one["browser_lane"]}
    )
    assert len(one["browser_lane"]) == 64 and one["browser_lane"] != "forged"
    assert two["browser_lane"] != one["browser_lane"]
    with pytest.raises(OctopError, match="another expert"):
        executions._prepare(owner, first.context_id, "browser.state", {}, actor_agent_id="expert-b")
    with pytest.raises(OctopError, match="not found"):
        executions._prepare(other, first.context_id, "browser.state", {})
    with pytest.raises(OctopError, match="CLIENT_OUTDATED"):
        await executions.call(owner, first.context_id, "browser.open", {})
    service.disconnect(connection)
    await executor.close()


async def test_browser_queue_rejected_through_raw_context_api_and_model_tool(fleet: Any) -> None:
    from types import SimpleNamespace

    from octop.api.routers.devices import CallBody, submit
    from octop.infra.devices.protocol import ledger_result
    from octop.infra.devices.tools import build_device_tools

    service, owner, _, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "browser-queue")
    device_id = enrolled["device"]["device_id"]
    executions = ExecutionService(service)
    context = executions.resolve(owner, device_id=device_id, agent_id="expert")
    actions = {
        "browser.action": {"command": "type", "text": "PRIVATE_TYPED_SECRET"},
        "browser.observe": {},
    }
    try:
        tool = next(t for t in build_device_tools(service, "expert") if t.name == "device_run")
        for action, params in actions.items():
            with pytest.raises(OctopError, match="immediate execution context API"):
                service.submit(owner, device_id, action, params)
            with pytest.raises(OctopError, match="immediate execution context API"):
                await submit(
                    device_id,
                    CallBody(action=action, params=params),
                    SimpleNamespace(id=owner),
                    service,
                )
            with pytest.raises(OctopError, match="immediate execution context API"):
                executions.submit(
                    owner, context.context_id, action, params, actor_agent_id="expert"
                )
            token = var_child_runnable_config.set(
                {"configurable": {"user": owner, "octop_execution_context": context.public()}}
            )
            try:
                response = await tool.ainvoke(
                    {"device_id": device_id, "action": action, "params": params}
                )
            finally:
                var_child_runnable_config.reset(token)
            assert "immediate execution context API" in response
        assert service.repos.device_repo.list_operations(owner) == []
        assert (
            ledger_result(
                "browser.observe", {"text": "PRIVATE_DOM_BODY", "elements": [{"text": "secret"}]}
            )
            == {}
        )
        assert ledger_result("browser.action", {"result": "PRIVATE_JS_RESULT"}) == {}
    finally:
        service.disconnect(connection)
        await executor.close()


async def test_browser_raw_calls_cannot_select_a_lane_or_bypass_context_policy(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from octop.api.routers.devices import CallBody, call

    service, owner, other, tmp = fleet
    for agent in ("caller", "victim"):
        service.repos.agent_repo.create(agent_id=agent, user_id=owner, name=agent)
        service.repos.thread_repo.insert(
            thread_id=agent + "-thread",
            agent_id=agent,
            user_id=owner,
            channel_type="dashboard",
            session_key=agent,
        )
    enrolled, executor, connection, messages = await attach(service, owner, tmp / "browser-call")
    device_id = enrolled["device"]["device_id"]
    row = service.owned(owner, device_id)
    await service.receive(
        connection,
        {
            "type": "policy_applied",
            "policy_revision": row.policy_revision,
            "trust_mode": "owner",
            "runtime": {"browser_protocol_version": 1},
        },
    )
    executions = ExecutionService(service)
    caller = executions.resolve(
        owner, device_id=device_id, agent_id="caller", thread_id="caller-thread"
    )
    victim = executions.resolve(
        owner, device_id=device_id, agent_id="victim", thread_id="victim-thread"
    )
    victim_lane = hashlib.sha256(
        json.dumps([owner, "victim", "victim-thread"]).encode()
    ).hexdigest()
    forged = {"browser_lane": victim_lane, "execution_context_id": victim.context_id}

    async def browser_reply(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"text": "PRIVATE_DOM_BODY", "session_id": "session"}

    monkeypatch.setattr(executor, "execute", browser_reply)
    try:
        with pytest.raises(OctopError, match="require an execution context"):
            await service.call(owner, device_id, "browser.observe", forged, agent_id="caller")
        with pytest.raises(OctopError, match="require an execution context"):
            await call(
                device_id,
                CallBody(action="browser.observe", params=forged, agent_id="caller"),
                SimpleNamespace(id=owner),
                service,
            )
        assert not any(message["type"] == "request" for message in messages)
        response = await executions.call(
            owner, caller.context_id, "browser.observe", forged, actor_agent_id="caller"
        )
        request = next(message for message in messages if message["type"] == "request")
        assert (
            request["params"]["browser_lane"]
            == hashlib.sha256(json.dumps([owner, "caller", "caller-thread"]).encode()).hexdigest()
        )
        assert request["params"]["execution_context_id"] == caller.context_id
        assert response["result"]["text"] == "PRIVATE_DOM_BODY"
        assert service.repos.device_repo.list_operations(owner) == []
        with pytest.raises(OctopError, match="another expert"):
            await service.call(
                owner,
                device_id,
                "browser.observe",
                forged,
                agent_id="caller",
                execution_context_id=victim.context_id,
            )
        with pytest.raises(OctopError, match="not found"):
            await service.call(
                other, device_id, "browser.observe", {}, execution_context_id=caller.context_id
            )
        with pytest.raises(OctopError, match="another device"):
            await service.call(
                owner,
                "different-device",
                "browser.observe",
                {},
                execution_context_id=caller.context_id,
            )
        plan = executions.resolve(owner, device_id=device_id, agent_id="caller", work_mode="plan")
        with pytest.raises(OctopError, match="only permits observation"):
            await service.call(
                owner,
                device_id,
                "browser.action",
                {"command": "type"},
                execution_context_id=plan.context_id,
            )
        await service.set_policy(owner, device_id, trust_mode="owner", working_dir=str(tmp))
        with pytest.raises(OctopError, match="policy changed"):
            await service.call(
                owner, device_id, "browser.observe", {}, execution_context_id=caller.context_id
            )
    finally:
        service.disconnect(connection)
        await executor.close()


async def test_explicit_account_default_resolves_after_session_and_expert_without_target_fallback(
    fleet: Any,
) -> None:
    import json

    service, owner, other, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        user_id=owner,
        agent_id="expert",
        channel_type="dashboard",
        session_key="test",
    )
    one, ex_one, c_one, _ = await attach(service, owner, tmp / "one")
    two, ex_two, c_two, _ = await attach(service, owner, tmp / "two")
    first, second = one["device"]["device_id"], two["device"]["device_id"]
    executions = ExecutionService(service)
    try:
        with pytest.raises(OctopError, match="choose an execution device"):
            executions.resolve(owner, agent_id="expert")
        service.repos.user_repo.set_preferences_json(
            owner, json.dumps({"timezone": "Asia/Shanghai"})
        )
        executions.save_default_target(owner, first, "/account/work")
        assert (
            json.loads(service.repos.user_repo.get(owner).preferences_json)["timezone"]
            == "Asia/Shanghai"
        )
        default = executions.resolve(owner, agent_id="expert")
        assert (default.device_id, default.working_dir, default.source) == (
            first,
            "/account/work",
            "account_default",
        )
        assert ExecutionService(service).default_target(owner)["device_id"] == first
        with pytest.raises(OctopError):
            executions.save_default_target(other, first, None)
        expert = executions.resolve(
            owner, agent_id="expert", binding={"device_id": second, "working_dir": "/expert/work"}
        )
        assert (expert.device_id, expert.working_dir, expert.source) == (
            second,
            "/expert/work",
            "expert_default",
        )
        executions.save_selection(
            owner, "thread", {"device_id": first, "working_dir": "/session/work"}
        )
        session = executions.resolve(
            owner,
            agent_id="expert",
            thread_id="thread",
            binding={"device_id": second, "working_dir": "/expert/work"},
        )
        assert (session.device_id, session.working_dir, session.source) == (
            first,
            "/session/work",
            "session_selection",
        )
        explicit = executions.resolve(
            owner, agent_id="expert", thread_id="thread", device_id=second
        )
        assert explicit.working_dir != "/session/work"
        with pytest.raises(OctopError):
            executions.resolve(owner, agent_id="expert", device_id="removed-device")
        with pytest.raises(OctopError):
            executions.resolve(
                owner, agent_id="expert", binding={"device_id": "removed-expert-device"}
            )
        assert executions.get(owner, default.context_id).device_id == first
        executions.save_default_target(owner, None, None)
        assert executions.default_target(owner)["device_id"] is None
    finally:
        service.disconnect(c_one)
        service.disconnect(c_two)
        await ex_one.close()
        await ex_two.close()


async def test_capability_catalog_obeys_device_owner_and_protocol_gate(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.devices import capabilities
    from octop.infra.execution.skills import ExecutionSkillService

    service, owner, other, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    device_id = enrolled["device"]["device_id"]
    executions = ExecutionService(service)
    context = executions.resolve(owner, device_id=device_id, agent_id="expert", work_mode="ask")
    sources = ExecutionSkillService(executions)
    with pytest.raises(OctopError, match="CLIENT_OUTDATED"):
        await sources.discover(owner, context.context_id, "expert")
    row = service.owned(owner, device_id)
    await service.receive(
        connection,
        {
            "type": "policy_applied",
            "policy_revision": row.policy_revision,
            "trust_mode": "owner",
            "runtime": {"capability_protocol_version": 1},
        },
    )
    directory = tmp / "home" / ".codex" / "skills" / "review"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: Device review\n---\nBody", encoding="utf-8")
    discover = capabilities.discover
    inspect = capabilities.inspect_skill
    monkeypatch.setattr(capabilities, "discover", lambda: discover(tmp / "home"))
    monkeypatch.setattr(
        capabilities,
        "inspect_skill",
        lambda source, slug, digest: inspect(source, slug, digest, tmp / "home"),
    )
    candidates = await sources.discover(owner, context.context_id, "expert")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["device_id"] == device_id
    assert candidate["needs_inspection"] is True
    package = await sources.package(
        owner, context.context_id, "expert", "codex", "review", candidate["digest"]
    )
    assert "Device review" in dict(package.files)["SKILL.md"].decode()
    with pytest.raises(OctopError, match="not found"):
        await sources.discover(other, context.context_id, "expert")
    service.disconnect(connection)
    await executor.close()


async def test_run_receipts_correlate_requests_files_and_durable_operations(fleet: Any) -> None:
    from octop.infra.execution.events import RunInspectionService
    from octop.infra.execution.inspection import RequestInspectionService

    service, owner, other, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    executions = ExecutionService(service)
    context = executions.resolve(
        owner,
        device_id=enrolled["device"]["device_id"],
        agent_id="expert",
        thread_id="thread",
        run_id="run-demo",
    )
    await executions.call(
        owner,
        context.context_id,
        "fs.write",
        {"path": "result.txt", "data_b64": base64.b64encode(b"private file body").decode()},
        actor_agent_id="expert",
    )
    await executions.call(owner, context.context_id, "fs.read", {"path": "result.txt"})
    RequestInspectionService(service.repos).record(
        "expert",
        {
            "owner_user_id": owner,
            "request_id": "model-request",
            "thread_id": "thread",
            "run_id": "run-demo",
            "context_id": context.context_id,
            "created_at": 1,
            "status": "completed",
            "components": [],
            "estimated_input_tokens": 15,
        },
    )
    history = RunInspectionService(service.repos)
    events = history.list(owner, "expert", "thread", run_id="run-demo")["events"]
    assert len(events) == 3
    assert {event["kind"] for event in events} == {"model", "device"}
    assert all(
        event["status"] == "completed" and event["context_id"] == context.context_id
        for event in events
    )
    write = next(event for event in events if event["payload"].get("action") == "fs.write")
    operation = service.operation(owner, write["payload"]["operation_id"])
    assert operation.status == "completed"
    assert write["payload"]["receipt"]["sha256"]
    assert "private file body" not in str(events)
    assert "data_b64" not in str(events)
    with pytest.raises(OctopError, match="unavailable"):
        history.list(other, "expert", "thread")
    with pytest.raises(OctopError, match="another expert"):
        await executions.call(
            owner,
            context.context_id,
            "fs.read",
            {"path": "result.txt"},
            actor_agent_id="different-expert",
        )
    page = history.list(owner, "expert", "thread", limit=1)
    assert page["has_more"]
    assert len(history.list(owner, "expert", "thread", before=page["next_before"])["events"]) == 2
    service.disconnect(connection)
    await executor.close()


async def test_interrupted_receipt_is_unknown_and_job_observation_is_not_submission_success(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.execution.events import RunInspectionService

    service, owner, _, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    executions = ExecutionService(service)
    context = executions.resolve(
        owner,
        device_id=enrolled["device"]["device_id"],
        agent_id="expert",
        thread_id="thread",
        run_id="cancelled-run",
    )

    async def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(service, "call", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await executions.call(owner, context.context_id, "fs.write", {"path": "unknown.txt"})
    history = RunInspectionService(service.repos)
    history.job_observation(
        context, {"job_id": "training", "status": "running", "context_id": "original-context"}
    )
    history.job_observation(context, {"job_id": "training", "status": "completed", "returncode": 0})
    events = history.list(owner, "expert", "thread")["events"]
    assert len(events) == 2
    assert {event["kind"]: event["status"] for event in events} == {
        "job": "completed",
        "device": "unknown",
    }
    service.disconnect(connection)
    await executor.close()


async def test_direct_and_queued_commands_record_nonzero_exit_as_failure(fleet: Any) -> None:
    from octop.infra.execution.events import RunInspectionService

    service, owner, _, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    executions = ExecutionService(service)
    context = executions.resolve(
        owner, device_id=enrolled["device"]["device_id"], agent_id="expert", thread_id="thread"
    )
    params = {"argv": [sys.executable, "-c", "raise SystemExit(7)"]}
    assert (await executions.call(owner, context.context_id, "command.run", params))["result"][
        "returncode"
    ] == 7
    submitted = executions.submit(
        owner, context.context_id, "command.run", params, actor_agent_id="expert"
    )
    await service._jobs[submitted["operation_id"]]
    history = RunInspectionService(service.repos).list(owner, "expert", "thread")["events"]
    assert len(history) == 2
    assert all(
        event["status"] == "failed" and event["payload"]["receipt"]["returncode"] == 7
        for event in history
    )
    service.disconnect(connection)
    await executor.close()


async def test_unknown_mutation_receipt_reconciles_the_same_run_event(fleet: Any) -> None:
    from octop.infra.execution.events import RunInspectionService

    service, owner, _, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    device_id = enrolled["device"]["device_id"]
    executions = ExecutionService(service)
    context = executions.resolve(
        owner, device_id=device_id, agent_id="expert", thread_id="thread", run_id="original-run"
    )
    late = {}

    async def lose_receipt(frame: dict[str, Any]) -> None:
        if frame["type"] == "request":
            result = await executor.execute(
                frame["id"],
                frame["action"],
                frame["params"],
                grant_version=frame["grant_version"],
                permissions=frame["permissions"],
            )
            late.update(type="result", id=frame["id"], ok=True, result=result)
            service.disconnect(connection)

    connection.send = lose_receipt
    try:
        with pytest.raises(OctopError, match="disconnected"):
            await executions.call(
                owner,
                context.context_id,
                "fs.write",
                {"path": "actual.txt", "data_b64": base64.b64encode(b"already written").decode()},
            )
        assert (tmp / "device" / "actual.txt").read_bytes() == b"already written"
        history = RunInspectionService(service.repos)
        before = history.list(owner, "expert", "thread")["events"]
        assert len(before) == 1 and before[0]["status"] == "unknown"

        async def ignore(frame: dict[str, Any]) -> None:
            pass

        async def close() -> None:
            pass

        reconnected = await service.connect(
            device_id, enrolled["device_token"], ignore, close, client_protocol_version=3
        )
        await service.receive(reconnected, late)
        after = history.list(owner, "expert", "thread")["events"]
        assert len(after) == 1 and after[0]["event_id"] == before[0]["event_id"]
        assert after[0]["status"] == "completed"
        assert after[0]["payload"]["receipt"]["sha256"]
        service.disconnect(reconnected)
    finally:
        service.disconnect(connection)
        await executor.close()


async def test_dashboard_context_binds_model_tools_and_peer_to_one_run(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.execution.events import RunInspectionService
    from octop.infra.execution.inspection import RequestInspectionService

    service, owner, _, tmp = fleet
    for agent in ("expert", "peer"):
        service.repos.agent_repo.create(agent_id=agent, user_id=owner, name=agent)
        service.repos.thread_repo.insert(
            thread_id=agent + "-thread",
            agent_id=agent,
            user_id=owner,
            channel_type="dashboard",
            session_key=agent,
        )
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "device")
    executions = ExecutionService(service)
    dashboard = executions.resolve(
        owner,
        device_id=enrolled["device"]["device_id"],
        agent_id="expert",
        thread_id="expert-thread",
    )
    assert dashboard.run_id is None
    manager = AgentManager.__new__(AgentManager)
    manager._device_service = service
    monkeypatch.setattr(manager, "get_config", lambda _agent: {})
    request = manager._prepare_stream_request(
        "expert",
        {
            "user": str(owner),
            "thread_id": "expert-thread",
            "configurable": {"octop_execution_context": dashboard.public()},
        },
    )
    cfg = request["configurable"]
    bound = executions.get(owner, cfg["octop_execution_context"]["context_id"])
    assert bound.run_id == cfg["octop_task_run_id"]
    assert bound.context_id != dashboard.context_id
    assert executions.get(owner, dashboard.context_id).run_id is None
    await executions.call(
        owner,
        bound.context_id,
        "fs.write",
        {"path": "artifact.txt", "data_b64": base64.b64encode(b"actual result").decode()},
        actor_agent_id="expert",
    )
    RequestInspectionService(service.repos).record(
        "expert",
        {
            "request_id": "actual-model-request",
            "owner_user_id": owner,
            "thread_id": "expert-thread",
            "run_id": cfg["octop_task_run_id"],
            "context_id": bound.context_id,
            "created_at": 1,
            "status": "completed",
            "components": [],
        },
    )
    events = RunInspectionService(service.repos).list(
        owner, "expert", "expert-thread", run_id=bound.run_id
    )["events"]
    assert {event["kind"] for event in events} == {"target", "device", "model"}
    peer = manager._prepare_stream_request(
        "peer", {"user": str(owner), "thread_id": "peer-thread", "configurable": cfg}
    )
    inherited = executions.get(owner, peer["configurable"]["octop_execution_context"]["context_id"])
    assert inherited.agent_id == "peer" and inherited.thread_id == "peer-thread"
    assert inherited.run_id == bound.run_id
    assert inherited.device_id == bound.device_id and inherited.working_dir == bound.working_dir
    assert inherited.policy_revision == bound.policy_revision
    await executions.call(
        owner, inherited.context_id, "fs.read", {"path": "artifact.txt"}, actor_agent_id="peer"
    )
    service.disconnect(connection)
    await executor.close()


async def test_saved_plan_mode_controls_harness_even_without_selected_device(
    fleet: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentManager

    service, owner, _, _ = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="thread",
    )
    ExecutionService(service).save_selection(owner, "thread", {"work_mode": "plan"})
    manager = AgentManager.__new__(AgentManager)
    manager._device_service = service
    monkeypatch.setattr(manager, "get_config", lambda _agent: {})
    request = manager._prepare_stream_request(
        "expert", {"user": str(owner), "thread_id": "thread", "conversation_mode": "craft"}
    )
    assert request["conversation_mode"] == "plan"
    assert request["configurable"]["conversation_mode"] == "plan"


async def test_owner_command_uses_requested_os_directory_without_confirmation(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    result = await service.call(
        owner,
        enrolled["device"]["device_id"],
        "command.run",
        {"argv": [sys.executable, "-c", "import os; print(os.getcwd())"], "cwd": str(tmp)},
    )
    assert result["returncode"] == 0
    assert Path(result["stdout"].strip()).resolve() == tmp.resolve()
    service.disconnect(connection)
    await executor.close()


async def test_policy_pending_blocks_execution_until_device_reports(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(
        service, owner, tmp / "project", acknowledge=False
    )
    with pytest.raises(OctopError, match="POLICY_PENDING"):
        await service.call(owner, enrolled["device"]["device_id"], "fs.list", {"path": "."})
    service.disconnect(connection)
    await executor.close()


async def test_other_account_cannot_change_trust_policy(fleet: Any) -> None:
    service, owner, other, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    with pytest.raises(OctopError):
        await service.set_policy(other, enrolled["device"]["device_id"], trust_mode="owner")
    service.disconnect(connection)
    await executor.close()


async def test_owner_screen_switch_does_not_request_device_consent(
    fleet: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        DeviceExecutor,
        "capabilities",
        property(
            lambda _: [
                "desktop_view",
                "desktop_control",
                "files_read",
                "files_write",
                "command_exec",
            ]
        ),
    )
    service, owner, _, tmp = fleet
    enrolled, executor, connection, messages = await attach(service, owner, tmp / "project")
    result = await service.request_desktop_switch(
        owner, enrolled["device"]["device_id"], mode="view_control"
    )
    assert result["status"] == "accepted"
    assert all(frame["type"] != "desktop_takeover" for frame in messages)
    service.disconnect(connection)
    await executor.close()


async def test_policy_disabling_write_is_enforced_after_device_ack(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    device_id = enrolled["device"]["device_id"]
    updated = await service.set_policy(
        owner, device_id, trust_mode="owner", permissions=["files_read"], working_dir=str(tmp)
    )
    assert updated["policy_revision"] == updated["applied_policy_revision"]
    with pytest.raises(OctopError, match="capability not granted"):
        await service.call(owner, device_id, "fs.write", {"path": "new.txt", "data_b64": ""})
    service.disconnect(connection)
    await executor.close()


@pytest.mark.parametrize("permissions", [["files_read"], []])
async def test_saved_owner_policy_preserves_disabled_capabilities(
    tmp_path: Path, permissions: list[str]
) -> None:
    client = DeviceClient(tmp_path / "state")
    save_private_json(
        client.state_path,
        {
            "device_id": "sample",
            "device_token": "odv_sample",
            "server_url": "https://controller.test",
            "policy": {
                "permissions": permissions,
                "roots": [],
                "trust_mode": "owner",
                "working_dir": str(tmp_path),
            },
        },
    )
    executor = client.saved_executor()
    assert executor.trust_mode == "owner"
    assert executor.permissions == set(permissions)
    with pytest.raises(DeviceExecutionError, match="permission denied"):
        await executor.execute(
            "write",
            "fs.write",
            {"path": "blocked.txt", "data_b64": ""},
            grant_version=0,
            permissions=["files_write"],
        )
    await executor.close()


async def test_execution_context_is_persistent_and_selected_device_overrides_default(
    fleet: Any,
) -> None:
    service, owner, other, tmp = fleet
    first, first_executor, first_connection, _ = await attach(service, owner, tmp / "first")
    second, second_executor, second_connection, _ = await attach(service, owner, tmp / "second")
    (tmp / "first" / "marker.txt").write_text("first")
    (tmp / "second" / "marker.txt").write_text("second")
    executions = ExecutionService(service)
    context = executions.resolve(
        owner,
        device_id=second["device"]["device_id"],
        binding={"device_id": first["device"]["device_id"], "working_dir": str(tmp / "first")},
    )
    value = await executions.call(owner, context.context_id, "fs.read", {"path": "marker.txt"})
    assert base64.b64decode(value["result"]["data_b64"]) == b"second"
    assert context.source == "session_selection"
    assert ExecutionService(service).get(owner, context.context_id) == context
    with pytest.raises(OctopError, match="not found"):
        executions.get(other, context.context_id)
    service.disconnect(first_connection)
    service.disconnect(second_connection)
    await first_executor.close()
    await second_executor.close()


async def test_plan_context_can_observe_but_cannot_execute(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    executions = ExecutionService(service)
    context = executions.resolve(owner, device_id=enrolled["device"]["device_id"], work_mode="plan")
    assert (
        "entries"
        in (await executions.call(owner, context.context_id, "fs.list", {"path": "."}))["result"]
    )
    with pytest.raises(OctopError, match="only permits observation"):
        await executions.call(
            owner,
            context.context_id,
            "command.run",
            {"argv": [sys.executable, "-c", "print('unexpected')"]},
        )
    service.disconnect(connection)
    await executor.close()


async def test_context_rejects_policy_change_instead_of_silently_using_new_scope(
    fleet: Any,
) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    executions = ExecutionService(service)
    device_id = enrolled["device"]["device_id"]
    context = executions.resolve(owner, device_id=device_id)
    await service.set_policy(owner, device_id, trust_mode="owner", working_dir=str(tmp))
    with pytest.raises(OctopError, match="execution policy changed"):
        await executions.call(owner, context.context_id, "fs.list", {"path": "."})
    service.disconnect(connection)
    await executor.close()


async def test_existing_job_observation_reauthorizes_current_grants_after_directory_change(
    fleet: Any,
) -> None:
    service, owner, _, tmp = fleet
    enrolled, executor, connection, _ = await attach(service, owner, tmp / "project")
    device_id = enrolled["device"]["device_id"]
    await service.receive(
        connection,
        {
            "type": "policy_applied",
            "policy_revision": service.owned(owner, device_id).policy_revision,
            "trust_mode": "owner",
            "runtime": {"job_protocol_version": 1},
        },
    )
    executions = ExecutionService(service)
    context = executions.resolve(owner, device_id=device_id)
    accepted = (
        await executions.call(
            owner,
            context.context_id,
            "jobs.start",
            {
                "argv": [sys.executable, "-c", "pass"],
                "idempotency_key": "policy-change-observation",
            },
        )
    )["result"]
    try:
        await service.set_policy(owner, device_id, trust_mode="owner", working_dir=str(tmp))
        # The fake client's follow-up receipt also reports its implemented versions.
        await service.receive(
            connection,
            {
                "type": "policy_applied",
                "policy_revision": service.owned(owner, device_id).policy_revision,
                "trust_mode": "owner",
                "runtime": {"job_protocol_version": 1},
            },
        )
        observed = (
            await executions.call(
                owner, context.context_id, "jobs.status", {"job_id": accepted["job_id"]}
            )
        )["result"]
        assert (
            observed["context_id"] == context.context_id
            and observed["job_id"] == accepted["job_id"]
        )
        with pytest.raises(OctopError, match="execution policy changed"):
            await executions.call(
                owner,
                context.context_id,
                "jobs.start",
                {
                    "argv": [sys.executable, "-c", "pass"],
                    "idempotency_key": "new-not-allowed",
                },
            )
        await service.revoke(owner, device_id)
        with pytest.raises(OctopError):
            await executions.call(
                owner, context.context_id, "jobs.status", {"job_id": accepted["job_id"]}
            )
    finally:
        executor.stop_jobs()
        service.disconnect(connection)
        await executor.close()


async def test_invalid_working_directory_reports_error_without_stopping_client(
    tmp_path: Path,
) -> None:
    client = DeviceClient(tmp_path / "state")
    executor = DeviceExecutor([], [], trust_mode="owner", working_dir=str(tmp_path))
    save_private_json(
        client.state_path,
        {
            "device_id": "sample",
            "device_token": "odv_sample",
            "server_url": "https://controller.test",
            "policy": {
                "permissions": ["files_read"],
                "roots": [],
                "trust_mode": "owner",
                "working_dir": str(tmp_path),
                "policy_revision": 0,
            },
        },
    )
    frames: list[Any] = []

    class Socket:
        async def send(self, value: str) -> None:
            import json

            frames.append(json.loads(value))

    await client.apply_policy_frame(
        Socket(),
        executor,
        {
            "policy_revision": 1,
            "controller_id": "controller-one",
            "trust_mode": "owner",
            "permissions": ["files_read"],
            "working_dir": str(tmp_path / "missing"),
        },
    )
    assert frames[-1]["type"] == "policy_rejected"
    assert executor.working_dir == tmp_path.resolve()
    assert client.load_state()["policy"]["policy_revision"] == 0
    await client.apply_policy_frame(
        Socket(),
        executor,
        {
            "policy_revision": 2,
            "controller_id": "controller-one",
            "trust_mode": "owner",
            "permissions": ["files_read"],
            "working_dir": str(tmp_path),
        },
    )
    assert frames[-1]["type"] == "policy_applied"
    assert client.load_state()["policy"]["policy_revision"] == 2
    await executor.close()


async def test_standard_backend_tools_keep_parallel_targets_separate(fleet: Any) -> None:
    service, owner, _, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    first, first_executor, first_connection, _ = await attach(service, owner, tmp / "first")
    second, second_executor, second_connection, _ = await attach(service, owner, tmp / "second")
    executions = ExecutionService(service)
    a = executions.resolve(owner, device_id=first["device"]["device_id"], agent_id="expert")
    b = executions.resolve(owner, device_id=second["device"]["device_id"], agent_id="expert")
    backend = RequestExecutionBackend(executions, "expert")

    async def use(context: Any, marker: str) -> None:
        token = var_child_runnable_config.set(
            {"configurable": {"user": owner, "octop_execution_context": context.public()}}
        )
        try:
            assert not (await backend.awrite("marker.txt", marker)).error
            assert not (await backend.aedit("marker.txt", marker, marker + " edited")).error
            result = await backend.aread("marker.txt")
            assert result.file_data["content"] == marker + " edited"
            found = await backend.agrep("edited", max_count=1)
            assert len(found.matches) == 1
            globbed = await backend.aglob("*.txt")
            assert len(globbed.matches) == 1
        finally:
            var_child_runnable_config.reset(token)

    await asyncio.gather(use(a, "first"), use(b, "second"))
    assert (tmp / "first" / "marker.txt").read_text() == "first edited"
    assert (tmp / "second" / "marker.txt").read_text() == "second edited"
    assert not (tmp / "marker.txt").exists()
    service.disconnect(first_connection)
    service.disconnect(second_connection)
    await first_executor.close()
    await second_executor.close()


async def test_saved_owner_reconnects_with_missing_default_directory(tmp_path: Path) -> None:
    client = DeviceClient(tmp_path / "state")
    missing = tmp_path / "renamed-project"
    save_private_json(
        client.state_path,
        {
            "device_id": "same-device",
            "device_token": "odv_preserved",
            "server_url": "https://controller.test",
            "policy": {
                "permissions": ["files_read"],
                "roots": [],
                "trust_mode": "owner",
                "working_dir": str(missing),
            },
        },
    )
    executor = client.saved_executor()
    absolute = tmp_path / "file.txt"
    absolute.write_text("still accessible")
    result = await executor.execute(
        "read", "fs.read", {"path": str(absolute)}, grant_version=0, permissions=["files_read"]
    )
    assert base64.b64decode(result["data_b64"]) == b"still accessible"
    assert client.load_state()["device_id"] == "same-device"
    executor.apply_policy("owner", ["files_read"], str(tmp_path))
    assert executor.working_dir == tmp_path.resolve()
    await executor.close()


def test_edit_follows_symlink_and_remove_only_removes_link(tmp_path: Path) -> None:
    original = tmp_path / "original.txt"
    original.write_text("before", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(original.name)
    except OSError:
        pytest.skip("OS account cannot create symlinks")
    fs = NativeFileSystem(tmp_path)
    fs.execute("fs.edit", {"path": str(link), "old_string": "before", "new_string": "after"})
    assert link.is_symlink()
    assert original.read_text() == "after"
    fs.execute("fs.remove", {"path": str(link)})
    assert not link.exists()
    assert original.read_text() == "after"


async def test_cancelled_write_cannot_commit_after_policy_revocation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import octop.infra.devices.filesystem as module

    entered, released = threading.Event(), threading.Event()
    real_fsync = module.os.fsync

    def gated_fsync(descriptor: int) -> None:
        real_fsync(descriptor)
        entered.set()
        assert released.wait(5)

    monkeypatch.setattr(module.os, "fsync", gated_fsync)
    executor = DeviceExecutor(["files_write"], [], trust_mode="owner", working_dir=str(tmp_path))
    task = asyncio.create_task(
        executor.execute(
            "write",
            "fs.write",
            {"path": "blocked.txt", "data_b64": "eA=="},
            grant_version=0,
            permissions=["files_write"],
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    executor.update_grants(1, [], [])
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "blocked.txt").exists()
    assert executor._journal["write"]["state"] == "cancelled"
    await executor.close()


async def test_cancel_after_file_commit_keeps_completed_receipt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    entered, released = threading.Event(), threading.Event()
    original_execute = NativeFileSystem.execute

    def gated_execute(fs: NativeFileSystem, action: str, params: dict[str, Any]) -> dict[str, Any]:
        result = original_execute(fs, action, params)
        entered.set()
        assert released.wait(5)
        return result

    monkeypatch.setattr(NativeFileSystem, "execute", gated_execute)
    executor = DeviceExecutor(["files_write"], [], trust_mode="owner", working_dir=str(tmp_path))
    task = asyncio.create_task(
        executor.execute(
            "write",
            "fs.write",
            {"path": "completed.txt", "data_b64": "eA=="},
            grant_version=0,
            permissions=["files_write"],
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    released.set()
    assert (await task)["size"] == 1
    assert (tmp_path / "completed.txt").read_text() == "x"
    assert executor._journal["write"]["state"] == "completed"
    await executor.close()


def test_native_large_file_stat_skips_hash_and_edit_is_bounded(
    tmp_path: Path, monkeypatch: Any
) -> None:
    file = tmp_path / "checkpoint.bin"
    with file.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024)
    fs = NativeFileSystem(tmp_path)

    def no_hash(path: Path) -> str:
        raise AssertionError("large file stat must not hash checkpoint contents")

    monkeypatch.setattr(fs, "digest", no_hash)
    result = fs.execute("fs.stat", {"path": str(file)})
    assert result["sha256"] is None and result["hash_omitted"] is True
    assert result["size"] == 32 * 1024 * 1024
    with pytest.raises(ValueError, match="inline edit limit"):
        fs.execute("fs.edit", {"path": str(file), "old_string": "old", "new_string": "new"})
