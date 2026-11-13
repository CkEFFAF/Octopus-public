"""Generic callbacks are durable, scoped and never wait for a model response."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.config import var_child_runnable_config

from octop.api.deps import get_server, is_jwt_exempt_request
from octop.api.routers.wakeup_hooks import router
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.backend import RequestExecutionBackend
from octop.infra.execution.events import RunInspectionService
from octop.infra.execution.foreground_policy import foreground_wait_error, job_label_data
from octop.infra.execution.job_tools import build_job_tools
from octop.infra.execution.service import ExecutionService
from octop.infra.execution.wakeup_hooks import WakeupHookService


@pytest.fixture
async def hooks(tmp_path: Path) -> Any:
    db = SqlitePool(tmp_path / "hooks.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    other = repos.user_repo.create(username="other", password_hash="unused", role="user")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    for thread in ("origin", "later"):
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id="expert",
            user_id=owner,
            channel_type="dashboard",
            session_key=thread,
        )
    repos.secret_repo.get_or_create("jwt", lambda: b"test-only-signing-secret")
    devices = DeviceService(repos, local_state_dir=tmp_path / "runtime")
    service = WakeupHookService(ExecutionService(devices))
    yield service, owner, other, tmp_path
    await devices.shutdown()
    db.close()


def register(service: WakeupHookService, owner: int, **overrides: Any) -> dict[str, Any]:
    values = {
        "title": "外部资源就绪",
        "event_type": "custom.resource.ready",
        "purpose": "检查收到的数据并反馈",
        "idempotency_key": "ready-once",
    }
    values.update(overrides)
    return service.register(owner, "expert", "origin", **values)


def fake_cron() -> Any:
    rows: dict[str, Any] = {}

    async def create(spec: Any) -> Any:
        rows[spec.cron_id] = spec
        return spec

    return SimpleNamespace(get=rows.get, create=AsyncMock(side_effect=create), rows=rows)


@pytest.mark.parametrize(
    "data",
    [
        None,
        "plain text",
        [1, "ready"],
        {"url": "https://example.invalid", "custom": {"ready": True}},
    ],
)
async def test_accepts_arbitrary_json_without_experiment_fields_and_deduplicates(
    hooks: Any, data: Any
) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    assert register(service, owner)["token"] == hook["token"]
    first = service.fire(hook["hook_id"], hook["token"], "custom.resource.ready", data)
    duplicate = service.fire(hook["hook_id"], hook["token"], "custom.resource.ready", data)
    assert first == {"accepted": True, "duplicate": False, "hook_id": hook["hook_id"]}
    assert duplicate["duplicate"] is True
    assert service.events.wakeup_hook(hook["hook_id"])["payload"]["data"] == data


async def test_scope_expiry_cancellation_and_payload_limits(hooks: Any) -> None:
    service, owner, other, _ = hooks
    hook = register(service, owner)
    with pytest.raises(OctopError):
        service.fire(hook["hook_id"], "wrong", "custom.resource.ready", None)
    with pytest.raises(ValueError):
        service.fire(hook["hook_id"], hook["token"], "another.type", None)
    with pytest.raises(ValueError):
        service.fire(hook["hook_id"], hook["token"], "custom.resource.ready", "x" * 8193)
    with pytest.raises(OctopError):
        service.cancel(other, "expert", "origin", hook["hook_id"])
    with pytest.raises(OctopError):
        service.cancel(owner, "expert", "later", hook["hook_id"])
    service.cancel(owner, "expert", "origin", hook["hook_id"])
    with pytest.raises(OctopError):
        service.fire(hook["hook_id"], hook["token"], "custom.resource.ready", None)
    expired = register(service, owner, idempotency_key="expired")
    row = service.events.wakeup_hook(expired["hook_id"])
    service.events.compare_payload(
        owner, row["event_id"], row["payload"], {**row["payload"], "expires_at": 1}, "waiting"
    )
    with pytest.raises(OctopError):
        service.fire(expired["hook_id"], expired["token"], "custom.resource.ready", {})


async def test_recovery_schedules_once_in_original_thread_after_binding_changes(hooks: Any) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {"message": "ready"})
    cron = fake_cron()
    # Recreate both service and polling turn as after a hub restart.
    await WakeupHookService(service.execution).tick(cron)
    await WakeupHookService(service.execution).tick(cron)
    cron.create.assert_awaited_once()
    spec = next(iter(cron.rows.values()))
    assert spec.meta["origin_thread_id"] == "origin"
    assert spec.meta["wakeup_hook_id"] == hook["hook_id"]
    assert spec.meta["max_fires"] == 1 and spec.fresh_thread is False
    assert service.repos.session_repo.get(spec.session_key).thread_id == "origin"


async def test_unfired_custom_hooks_do_not_starve_a_queued_event(hooks: Any) -> None:
    service, owner, _, _ = hooks
    for number in range(135):
        register(service, owner, idempotency_key=f"waiting-{number}")
    queued = register(service, owner, idempotency_key="queued")
    service.fire(queued["hook_id"], queued["token"], queued["event_type"], {})
    cron = fake_cron()
    await service.tick(cron)
    cron.create.assert_awaited_once()
    assert service.events.wakeup_hook(queued["hook_id"])["status"] == "scheduled"


async def test_job_terminal_receipt_wakes_but_unknown_does_not(hooks: Any) -> None:
    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    job_ref = f"job:{context.context_id}:existing-job"
    hook = register(service, owner, context_id=context.context_id, job_event_id=job_ref)
    inspection = RunInspectionService(service.repos)
    cron = fake_cron()
    for state in ["running", "unknown"]:
        inspection.job_observation(
            context, {"job_id": "existing-job", "status": state, "title": "核对文件索引"}
        )
        await service.tick(cron)
    cron.create.assert_not_awaited()
    inspection.job_observation(
        context, {"job_id": "existing-job", "status": "failed", "returncode": 3}
    )
    await service.tick(cron)
    cron.create.assert_awaited_once()
    assert service.events.wakeup_hook(hook["hook_id"])["payload"]["data"]["status"] == "failed"
    assert service.events.get(owner, job_ref)["payload"]["title"] == "核对文件索引"


async def test_callback_http_is_scoped_bounded_and_returns_before_any_model(hooks: Any) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        app_runtime=SimpleNamespace(execution=service.execution)
    )

    @app.exception_handler(OctopError)
    async def error(_request: Request, exc: OctopError) -> JSONResponse:
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    url = f"/api/wakeup-hooks/{hook['hook_id']}/fire"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(url, json={"event_type": hook["event_type"]})).status_code == 401
        headers = {"X-Octop-Wakeup-Token": hook["token"]}
        response = await client.post(
            url, headers=headers, json={"event_type": hook["event_type"], "data": ["custom", 1]}
        )
        assert response.status_code == 202 and response.json()["accepted"] is True
        assert (await client.post(url, headers=headers, content=b"x" * 12289)).status_code == 413
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "queued"
    request = Request({"type": "http", "method": "POST", "path": url, "headers": []})
    assert is_jwt_exempt_request(request)
    assert not is_jwt_exempt_request(
        Request({"type": "http", "method": "GET", "path": url, "headers": []})
    )
    assert not is_jwt_exempt_request(
        Request({"type": "http", "method": "POST", "path": url + "/other", "headers": []})
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("execute", {"command": "sleep 420; tail -3 probes.log", "timeout": 600}),
        ("execute", {"command": "sleep 7m; date"}),
        (
            "device_run",
            {"action": "command.run", "params": {"argv": ["bash", "-lc", "sleep 420; date"]}},
        ),
        ("execute", {"command": "Start-Sleep -Seconds 420"}),
    ],
)
def test_foreground_rejects_long_waits_before_dispatch(name: str, args: dict[str, Any]) -> None:
    assert "job_start" in (foreground_wait_error(name, args, "en") or "")


@pytest.mark.parametrize(
    "command",
    [
        "sleep 1; tail -3 probes.log",
        'echo "sleep 420"',
        "python evaluate.py",
        "printf '%s' 'sleep 420'",
    ],
)
def test_short_commands_and_quoted_text_are_not_blocked(command: str) -> None:
    assert foreground_wait_error("execute", {"command": command}, "en") is None


def test_legacy_shell_job_labels_use_real_script_or_log_names() -> None:
    assert (
        job_label_data(["bash", "-lc", "cd /work && python -u train.py --config exp.yaml"])[
            "program"
        ]
        == "train.py"
    )
    assert job_label_data(["bash", "-lc", "tail -3 agent/out/probes.log; nvidia-smi"]) == {
        "program": "bash",
        "job_kind": "log_gpu",
        "subject": "probes.log",
    }


async def test_job_tool_requires_a_meaningful_name_and_returns_acceptance(hooks: Any) -> None:
    service, owner, _, _ = hooks
    backend = RequestExecutionBackend(service.execution, "expert")
    backend.call_operation = AsyncMock(return_value={"job_id": "accepted", "status": "running"})
    start = next(item for item in build_job_tools(backend) if item.name == "job_start")
    config = var_child_runnable_config.set(
        {"configurable": {"user": owner, "thread_id": "origin", "language": "zh"}}
    )
    try:
        result = await start.ainvoke(
            {"argv": ["python", "report.py"], "idempotency_key": "report", "title": "生成月度报告"}
        )
        assert json.loads(result)["job_id"] == "accepted"
        assert backend.call_operation.call_args.args[1]["title"] == "生成月度报告"
        backend.call_operation.reset_mock()
        assert "bash" in await start.ainvoke(
            {"argv": ["bash"], "idempotency_key": "bad", "title": "bash"}
        )
        backend.call_operation.assert_not_awaited()
    finally:
        var_child_runnable_config.reset(config)


async def test_cancelled_hook_cannot_be_resurrected_from_an_authenticated_snapshot(
    hooks: Any,
) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    stale = service.authenticate(hook["hook_id"], hook["token"])
    service.cancel(owner, "expert", "origin", hook["hook_id"])
    with pytest.raises(OctopError):
        service._queue(stale, hook["event_type"], {})
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "cancelled"


async def test_cancellation_while_cron_is_created_does_not_resurrect_hook(hooks: Any) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})
    cron = fake_cron()
    create = cron.create.side_effect

    async def cancel_during_create(spec: Any) -> Any:
        service.cancel(owner, "expert", "origin", hook["hook_id"])
        return await create(spec)

    cron.create.side_effect = cancel_during_create
    await service.tick(cron)
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "cancelled"


async def test_terminal_job_is_not_starved_by_128_older_nonterminal_hooks(hooks: Any) -> None:
    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    inspection = RunInspectionService(service.repos)
    for index in range(129):
        job_id = str(index)
        inspection.job_observation(
            context, {"job_id": job_id, "status": "running" if index < 128 else "completed"}
        )
        register(
            service,
            owner,
            context_id=context.context_id,
            idempotency_key=job_id,
            job_event_id=f"job:{context.context_id}:{job_id}",
        )
    cron = fake_cron()
    await service.tick(cron)
    cron.create.assert_awaited_once()


async def test_completion_intent_recovers_from_persisted_job_after_restart(hooks: Any) -> None:
    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    inspection = RunInspectionService(service.repos)
    inspection.job_observation(
        context,
        {
            "job_id": "accepted",
            "status": "running",
            "notify_on_exit": True,
            "resume_mode": "continue",
            "title": "生成报告",
        },
    )
    inspection.job_observation(context, {"job_id": "accepted", "status": "completed"})
    cron = fake_cron()
    await WakeupHookService(service.execution).tick(cron)
    await WakeupHookService(service.execution).tick(cron)
    cron.create.assert_awaited_once()
    spec = next(iter(cron.rows.values()))
    assert spec.name == "生成报告"
    assert (
        service.events.wakeup_hook(spec.meta["wakeup_hook_id"])["payload"]["resume_mode"]
        == "continue"
    )


async def test_progress_is_persisted_sequenced_and_never_schedules_a_model(hooks: Any) -> None:
    service, owner, _, root = hooks
    hook = register(service, owner, delivery_mode="progress")
    service.fire(
        hook["hook_id"],
        hook["token"],
        hook["event_type"],
        {"percent": 40, "phase": "检查文件", "message": "完成 4 / 10", "sequence": 10},
    )
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    reference = f"job:{context.context_id}:progress-job"
    inspection = RunInspectionService(service.repos)
    inspection.job_observation(
        context,
        {"job_id": "progress-job", "status": "running", "progress_hook_id": hook["hook_id"]},
    )
    # A restart between accepted receipt and binding must recover early script reports.
    cron = fake_cron()
    await WakeupHookService(service.execution).tick(cron)
    assert service.events.job_progress(owner, [reference])[reference]["percent"] == 40
    assert service.events.sidebar_jobs(owner, "expert")[0]["progress"]["percent"] == 40
    page = service.events.background_page(
        owner, "expert", lifecycle="active", thread="origin", offset=0, limit=20
    )
    assert page["items"][0]["progress"]["percent"] == 40
    assert "payload_json" not in page["items"][0]
    assert service.fire(
        hook["hook_id"], hook["token"], hook["event_type"], {"percent": 5, "sequence": 1}
    )["duplicate"]
    with pytest.raises(ValueError):
        service.fire(hook["hook_id"], hook["token"], hook["event_type"], {"message": "heartbeat"})
    service.fire(
        hook["hook_id"], hook["token"], hook["event_type"], {"phase": "准备归档", "sequence": 11}
    )
    assert "percent" not in service.events.job_progress(owner, [reference])[reference]
    inspection.job_observation(
        context, {"job_id": "progress-job", "status": "failed", "returncode": 2}
    )
    await service.tick(cron)
    cron.create.assert_not_awaited()
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "completed"
    assert service.events.get(owner, reference)["status"] == "failed"
    assert service.events.job_progress(owner + 1, [reference]) == {}


@pytest.mark.parametrize(
    "data",
    [
        {"percent": -1},
        {"percent": 101},
        {"percent": True},
        {"percent": float("nan")},
        {"sequence": -1},
        {"message": "x" * 301},
        {"done": "yes"},
    ],
)
async def test_invalid_progress_does_not_replace_a_valid_receipt(hooks: Any, data: Any) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner, delivery_mode="progress")
    with pytest.raises(ValueError):
        service.fire(hook["hook_id"], hook["token"], hook["event_type"], data)
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "waiting"


async def test_progress_reservation_rejects_a_second_submission_before_dispatch(
    hooks: Any, monkeypatch: Any
) -> None:
    service, owner, _, root = hooks
    hook = register(service, owner, delivery_mode="progress")
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    backend = service.execution.local_backend(owner)
    call = AsyncMock(
        return_value={"job_id": "first", "status": "running", "context_id": context.context_id}
    )
    monkeypatch.setattr(backend, "call", call)
    params = {
        "argv": ["python", "report.py"],
        "idempotency_key": "first",
        "title": "整理报告",
        "notify_on_exit": True,
        "progress_hook_id": hook["hook_id"],
    }
    await service.execution.call(
        owner, context.context_id, "jobs.start", params, actor_agent_id="expert"
    )
    await service.execution.call(
        owner, context.context_id, "jobs.start", params, actor_agent_id="expert"
    )
    assert call.await_count == 2  # Same submission remains a native idempotent replay.
    with pytest.raises(ValueError, match="another job submission"):
        await service.execution.call(
            owner,
            context.context_id,
            "jobs.start",
            {**params, "idempotency_key": "different"},
            actor_agent_id="expert",
        )
    assert call.await_count == 2


async def test_cross_thread_job_replay_does_not_rewrite_original_intent(
    hooks: Any, monkeypatch: Any
) -> None:
    service, owner, _, root = hooks
    contexts = [
        service.execution.resolve(
            owner, target_kind="local", agent_id="expert", thread_id=thread, working_dir=str(root)
        )
        for thread in ("origin", "later")
    ]
    original, later = contexts
    inspection = RunInspectionService(service.repos)
    inspection.job_observation(
        original,
        {"job_id": "original", "status": "running", "title": "原始任务", "notify_on_exit": True},
    )
    monkeypatch.setattr(
        service.execution.local_backend(owner),
        "call",
        AsyncMock(
            return_value={
                "job_id": "original",
                "status": "running",
                "context_id": original.context_id,
            }
        ),
    )
    with pytest.raises(OctopError, match="another execution origin"):
        await service.execution.call(
            owner,
            later.context_id,
            "jobs.start",
            {
                "argv": ["python", "report.py"],
                "idempotency_key": "same",
                "title": "错误标题",
                "notify_on_exit": False,
            },
            actor_agent_id="expert",
        )
    payload = service.events.get(owner, f"job:{original.context_id}:original")["payload"]
    assert payload["title"] == "原始任务" and payload["notify_on_exit"] is True


async def test_accepted_job_survives_temporary_completion_registration_failure(
    hooks: Any, monkeypatch: Any
) -> None:
    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    monkeypatch.setattr(
        service.execution.local_backend(owner),
        "call",
        AsyncMock(
            return_value={
                "job_id": "accepted",
                "status": "running",
                "context_id": context.context_id,
            }
        ),
    )
    original = WakeupHookService.register
    monkeypatch.setattr(WakeupHookService, "register", MagicMock(side_effect=OSError("temporary")))
    receipt = await service.execution.call(
        owner,
        context.context_id,
        "jobs.start",
        {
            "argv": ["python", "report.py"],
            "idempotency_key": "accepted",
            "title": "生成报告",
            "notify_on_exit": True,
        },
        actor_agent_id="expert",
    )
    assert receipt["result"]["completion_hook_status"] == "pending"
    monkeypatch.setattr(WakeupHookService, "register", original)
    await service.tick(fake_cron())
    assert service.events.jobs_without_completion_hook() == []


async def test_contextless_callback_does_not_inherit_a_later_device_and_denies_stale_tools(
    hooks: Any, monkeypatch: Any
) -> None:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.agents.middleware.work_mode import WorkModeMiddleware

    service, owner, _, _ = hooks
    manager = AgentManager.__new__(AgentManager)
    manager._device_service = service.execution.devices
    monkeypatch.setattr(
        manager, "get_config", lambda _agent: {"device_binding": {"device_id": "later-device"}}
    )
    request = manager._prepare_stream_request(
        "expert",
        {
            "user": str(owner),
            "thread_id": "origin",
            "configurable": {"octop_wakeup_event_only": True, "work_mode": "ask"},
        },
    )
    assert "octop_execution_context" not in request["configurable"]
    assert "octop_device_target" not in request["configurable"]
    middleware = WorkModeMiddleware(MagicMock(), "expert")
    cfg = var_child_runnable_config.set({"configurable": request["configurable"]})
    try:
        tool_request = SimpleNamespace(
            tool_call={"id": "stale", "name": "read_file", "args": {"file_path": "private.txt"}}
        )
        handler = MagicMock()
        assert middleware.wrap_tool_call(tool_request, handler).status == "error"
        handler.assert_not_called()
    finally:
        var_child_runnable_config.reset(cfg)


async def test_cancel_during_delivery_preparation_prevents_model_dispatch(
    hooks: Any, monkeypatch: Any
) -> None:
    from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService

    service, owner, _, _ = hooks
    hook = register(service, owner)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})
    manager = MagicMock()
    gateway = MagicMock()
    gateway.observe_dashboard_resume = AsyncMock()
    delivery = CronDeliveryService(gateway=gateway, agent_manager=manager, repos=service.repos)
    session = SimpleNamespace(
        user_id=owner,
        agent_id="expert",
        thread_id="origin",
        channel_type="dashboard",
        session_key="test",
    )
    command = CronDeliveryCommand(
        cron_id="event",
        cron_name="事件",
        agent_id="expert",
        user_id=owner,
        session_key="test",
        prompt="事件到达",
        fresh_thread=False,
        task_type="agent",
        model=None,
        mcp_servers=(),
        origin_thread_id="origin",
        wakeup_hook_id=hook["hook_id"],
    )

    async def prepare(*args: Any) -> dict[str, Any]:
        service.cancel(owner, "expert", "origin", hook["hook_id"])
        return {"messages": [], "thread_id": "origin"}

    monkeypatch.setattr(delivery, "_build_agent_request", prepare)
    with pytest.raises(ValueError, match="cancelled or already dispatched"):
        await delivery._deliver_agent(command, session)
    manager.stream.assert_not_called()
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "cancelled"


async def test_running_delivery_is_not_claimed_cancelled_and_restart_marks_uncertainty(
    hooks: Any,
) -> None:
    service, owner, _, _ = hooks
    hook = register(service, owner)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})
    row = service.events.wakeup_hook(hook["hook_id"])
    assert service.events.compare_payload(
        owner, hook["hook_id"], row["payload"], row["payload"], "running", expected_status="queued"
    )
    assert service.cancel(owner, "expert", "origin", hook["hook_id"])["status"] == "running"
    service.events.recover_wakeup_deliveries()
    assert service.events.wakeup_hook(hook["hook_id"])["status"] == "unknown"
    with pytest.raises(OctopError):
        service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})


async def test_callback_request_preserves_original_context_in_ask_mode(hooks: Any) -> None:
    from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService

    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    hook = register(service, owner, context_id=context.context_id)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})
    manager = MagicMock()
    manager.get_row.return_value = service.repos.agent_repo.get("expert")
    manager.default_mcp_servers.return_value = []
    manager.device_mcp_pack_for_turn.return_value = ([], [])
    manager.merge_turn_mcp_servers.return_value = []
    manager.default_knowledge_base_ids.return_value = []
    delivery = CronDeliveryService(gateway=MagicMock(), agent_manager=manager, repos=service.repos)
    session = SimpleNamespace(
        user_id=owner,
        agent_id="expert",
        thread_id="origin",
        channel_type="dashboard",
        session_key="test",
    )
    command = CronDeliveryCommand(
        cron_id="event",
        cron_name="事件",
        agent_id="expert",
        user_id=owner,
        session_key="test",
        prompt="事件到达",
        fresh_thread=False,
        task_type="agent",
        model=None,
        mcp_servers=(),
        origin_thread_id="origin",
        wakeup_hook_id=hook["hook_id"],
        wakeup_context_id=context.context_id,
    )
    request = await delivery._build_agent_request(command, session)
    assert request["conversation_mode"] == "ask"
    assert request["configurable"]["octop_execution_context"]["context_id"] == context.context_id
    from dataclasses import replace

    with pytest.raises(ValueError):
        await delivery._build_agent_request(
            replace(command, wakeup_context_id="later-context"), session
        )


@pytest.mark.parametrize("mode", ["ask", "plan", "agentic", "debug"])
async def test_explicit_continuation_keeps_original_mode_and_target(
    hooks: Any, monkeypatch: Any, mode: str
) -> None:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService

    service, owner, _, _ = hooks
    devices = service.execution.devices
    ids = [
        devices.enroll(
            owner_user_id=owner,
            name=name,
            platform="linux",
            capabilities=["files_read"],
            permissions=["files_read"],
            roots=[],
            trust_mode="restricted",
        )["device"]["device_id"]
        for name in ("original", "later")
    ]
    context = service.execution.resolve(
        owner, device_id=ids[0], agent_id="expert", thread_id="origin", work_mode=mode
    )
    hook = register(service, owner, context_id=context.context_id, resume_mode="continue")
    # External data cannot promote an Ask source or select the later device.
    service.fire(
        hook["hook_id"],
        hook["token"],
        hook["event_type"],
        {"work_mode": "agentic", "device_id": ids[1]},
    )
    manager = MagicMock()
    manager.get_row.return_value = service.repos.agent_repo.get("expert")
    manager.default_mcp_servers.return_value = []
    manager.device_mcp_pack_for_turn.return_value = ([], [])
    manager.merge_turn_mcp_servers.return_value = []
    manager.default_knowledge_base_ids.return_value = []
    delivery = CronDeliveryService(gateway=MagicMock(), agent_manager=manager, repos=service.repos)
    session = SimpleNamespace(
        user_id=owner,
        agent_id="expert",
        thread_id="origin",
        channel_type="dashboard",
        session_key="test",
    )
    command = CronDeliveryCommand(
        cron_id="event",
        cron_name="事件",
        agent_id="expert",
        user_id=owner,
        session_key="test",
        prompt="继续原任务",
        fresh_thread=False,
        task_type="agent",
        model=None,
        mcp_servers=(),
        origin_thread_id="origin",
        wakeup_hook_id=hook["hook_id"],
        wakeup_context_id=context.context_id,
    )
    request = await delivery._build_agent_request(command, session)
    assert request["configurable"]["work_mode"] == mode
    manager.device_mcp_pack_for_turn.assert_called_once_with(
        owner, agent_id="expert", thread_id="origin", resolved_device_id=ids[0]
    )
    actual = AgentManager.__new__(AgentManager)
    actual._device_service = devices
    monkeypatch.setattr(
        actual, "get_config", lambda _agent: {"device_binding": {"device_id": ids[1]}}
    )
    prepared = actual._prepare_stream_request("expert", request)
    bound = service.execution.get(
        owner, prepared["configurable"]["octop_execution_context"]["context_id"]
    )
    assert bound.device_id == ids[0] and bound.work_mode == mode
    assert hook["resume_mode"] == "continue" and hook["origin_work_mode"] == mode
    await devices.revoke(owner, ids[0])
    with pytest.raises(OctopError):
        actual._prepare_stream_request("expert", request)


async def test_contextless_and_progress_callbacks_cannot_request_continuation(hooks: Any) -> None:
    service, owner, _, root = hooks
    with pytest.raises(ValueError, match="bound execution source"):
        register(service, owner, resume_mode="continue")
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    with pytest.raises(ValueError, match="wake delivery"):
        register(
            service,
            owner,
            context_id=context.context_id,
            delivery_mode="progress",
            resume_mode="continue",
        )
    hook = register(service, owner, context_id=context.context_id)
    assert hook["resume_mode"] == "observe"
    with pytest.raises(ValueError, match="different event settings"):
        register(service, owner, context_id=context.context_id, resume_mode="continue")


@pytest.mark.parametrize(
    ("source_mode", "resume", "expected"),
    [
        ("agentic", "continue", "agentic"),
        ("agentic", "observe", "ask"),
        ("ask", "continue", "ask"),
        ("plan", "continue", "plan"),
    ],
)
async def test_timer_mode_freezes_authorized_target_and_write_access(
    hooks: Any,
    monkeypatch: Any,
    source_mode: str,
    resume: str,
    expected: str,
) -> None:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.cron.delivery import CronDeliveryService, command_from_row
    from octop.infra.cron.manager import CronManager
    from octop.infra.cron.tools import build_self_reminder_tools
    from octop.infra.gateway.threads import ThreadRegistry

    service, owner, _, root = hooks
    frozen = service.execution.resolve(
        owner,
        target_kind="local",
        agent_id="expert",
        thread_id="origin",
        working_dir=str(root),
        work_mode=source_mode,
    )
    registry = ThreadRegistry(
        session_repo=service.repos.session_repo, thread_repo=service.repos.thread_repo
    )
    manager = MagicMock()
    manager.get_row.return_value = service.repos.agent_repo.get("expert")
    manager.merge_turn_mcp_servers.return_value = []
    manager.default_knowledge_base_ids.return_value = []
    gateway = MagicMock(thread_registry=registry)
    delivery = CronDeliveryService(gateway=gateway, agent_manager=manager, repos=service.repos)
    cron = CronManager(
        gateway=gateway, delivery_service=delivery, repos=service.repos, timezone="UTC"
    )
    key = ThreadRegistry.dashboard_key(agent_id="expert", user_id=owner)
    service.repos.session_repo.upsert(
        session_key=key,
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        chat_type="dm",
        thread_id="origin",
    )
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "agent_id": "expert",
                "user": owner,
                "thread_id": "origin",
                "session_key": key,
                "octop_execution_context": frozen.public(),
                "work_mode": source_mode,
            }
        }
    )
    try:
        scheduled = await build_self_reminder_tools(cron)[0].ainvoke(
            {"in_minutes": 10, "purpose": "follow up", "resume_mode": resume}
        )
    finally:
        var_child_runnable_config.reset(token)
    row = cron.get(json.loads(scheduled)["reminder_id"])
    service.repos.session_repo.set_thread(key, "later")
    service.execution.save_selection(
        owner,
        "origin",
        {
            "work_mode": "ask" if source_mode == "agentic" else "agentic",
            "working_dir": str(root / "later"),
            "target_kind": "local",
        },
    )
    view = cron.public_view(row)
    assert (view["thread_id"], view["resume_mode"]) == ("origin", resume)
    from octop.infra.cron.origin_target import resolve_delivery_session

    command = command_from_row(row)
    session = resolve_delivery_session(
        command=command,
        session_repo=service.repos.session_repo,
        thread_repo=service.repos.thread_repo,
        gateway=gateway,
    )
    request = await delivery._build_agent_request(command, session)
    assert request["configurable"]["session_key"] == session.session_key != key
    actual = AgentManager.__new__(AgentManager)
    actual._device_service = service.execution.devices
    monkeypatch.setattr(actual, "get_config", lambda _: {})
    prepared = actual._prepare_stream_request("expert", request)
    bound = service.execution.get(
        owner, prepared["configurable"]["octop_execution_context"]["context_id"]
    )
    assert (bound.thread_id, bound.working_dir, bound.work_mode) == ("origin", str(root), expected)
    operation = service.execution.call(
        owner,
        bound.context_id,
        "fs.write",
        {"path": "followup.txt", "data_b64": "b2s=", "create_only": True},
        actor_agent_id="expert",
    )
    if expected == "agentic":
        await operation
        assert (root / "followup.txt").read_bytes() == b"ok"
    else:
        with pytest.raises(OctopError, match="only permits observation"):
            await operation
        assert not (root / "followup.txt").exists()


async def test_legacy_timer_mode_patch_requires_its_owners_explicit_thread_target(
    hooks: Any,
) -> None:
    from octop.api.routers.cron import CronPatchBody, patch_cron
    from octop.infra.cron.manager import CronManager

    service, owner, other, root = hooks
    cron = CronManager(
        gateway=MagicMock(), delivery_service=MagicMock(), repos=service.repos, timezone="UTC"
    )
    service.repos.cron_repo.create(
        cron_id="timer",
        name="check",
        agent_id="expert",
        user_id=owner,
        session_key="later",
        trigger="interval:60",
        prompt="check",
        kind="self_reminder",
        meta={"origin_thread_id": "origin", "max_fires": 3, "fires": 1},
    )
    server = SimpleNamespace(
        services=SimpleNamespace(agent_repo=service.repos.agent_repo),
        app_runtime=SimpleNamespace(
            cron_manager=cron,
            execution=service.execution,
            agent_registry=SimpleNamespace(get_row=service.repos.agent_repo.get),
        ),
    )

    async def patch(user, mode):
        return await patch_cron(
            "expert",
            "timer",
            CronPatchBody(resume_mode=mode),
            SimpleNamespace(id=user, is_admin=user == owner),
            server,
        )

    assert cron.public_view(cron.get("timer"))["resume_mode"] == "observe"
    with pytest.raises(OctopError):
        await patch(other, "continue")
    service.execution.save_selection(
        owner, "later", {"target_kind": "local", "working_dir": str(root)}
    )
    with pytest.raises(OctopError) as missing:
        await patch(owner, "continue")
    assert missing.value.status == 409
    service.execution.save_selection(
        owner, "origin", {"target_kind": "local", "working_dir": str(root), "work_mode": "plan"}
    )
    view = await patch(owner, "continue")
    assert (view["resume_mode"], view["remaining"], view["thread_id"]) == ("continue", 2, "origin")
    saved = service.execution.get(owner, view["meta"]["wakeup_context_id"])
    assert (saved.thread_id, saved.work_mode) == ("origin", "plan")
    assert (await patch(owner, "observe"))["resume_mode"] == "observe"


async def test_scheduled_completion_mode_can_change_before_dispatch(hooks: Any) -> None:
    from octop.infra.cron.delivery import CronDeliveryService, command_from_row
    from octop.infra.cron.manager import CronManager

    service, owner, _, root = hooks
    context = service.execution.resolve(
        owner, target_kind="local", agent_id="expert", thread_id="origin", working_dir=str(root)
    )
    hook = register(service, owner, context_id=context.context_id)
    service.fire(hook["hook_id"], hook["token"], hook["event_type"], {})
    manager = MagicMock()
    manager.get_row.return_value = service.repos.agent_repo.get("expert")
    manager.merge_turn_mcp_servers.return_value = []
    manager.default_knowledge_base_ids.return_value = []
    from octop.infra.gateway.threads import ThreadRegistry

    gateway = MagicMock(
        thread_registry=ThreadRegistry(
            session_repo=service.repos.session_repo, thread_repo=service.repos.thread_repo
        )
    )
    delivery = CronDeliveryService(gateway=gateway, agent_manager=manager, repos=service.repos)
    cron = CronManager(
        gateway=gateway, delivery_service=delivery, repos=service.repos, timezone="UTC"
    )
    await service.tick(cron)
    row = cron.get("event-" + hook["hook_id"])
    assert cron.public_view(row)["resume_mode"] == "observe"
    updated = await cron.set_resume_mode(
        row.cron_id, owner=owner, mode="continue", execution=service.execution
    )
    assert cron.public_view(updated)["resume_mode"] == "continue"
    session = service.repos.session_repo.get(updated.session_key)
    request = await delivery._build_agent_request(command_from_row(updated), session)
    assert request["conversation_mode"] == "craft"
    assert request["configurable"]["octop_execution_context"]["context_id"] == context.context_id
    assert "Continue the follow-up" in str(request["messages"]) or "继续" in str(
        request["messages"]
    )
