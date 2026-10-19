"""Real SQLite/resource tools verify bounded collaboration authority and snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langgraph.config import var_child_runnable_config

from octop.infra.agents.teams.collaboration import CollaborationService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.documents.resources import ResourceService
from octop.infra.documents.tools import build_resource_tools
from octop.infra.errors import OctopError
from octop.infra.utils.paths import PathLayout


class Workspace:
    def __init__(self) -> None:
        self.files = {"inbound/paper.txt": b"A paper with source text."}

    async def adownload_bytes(self, path: str) -> bytes | None:
        return self.files.get(path)


@dataclass(frozen=True)
class Options:
    target_policy: str = "member_default"
    device_id: str | None = None
    target_kind: str | None = None
    working_dir: str | None = None
    resource_ids: tuple[str, ...] = ()


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "state.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin")
    outsider = repos.user_repo.create(username="outsider", role="user")
    for agent, user in (("parent", owner), ("child", owner), ("other", outsider)):
        repos.agent_repo.create(agent_id=agent, user_id=user, name=agent)
    for thread, agent, user in (
        ("root", "parent", owner),
        ("child-thread", "child", owner),
        ("unrelated", "child", owner),
        ("foreign", "other", outsider),
    ):
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id=agent,
            user_id=user,
            channel_type="dashboard",
            session_key=thread,
        )
    workspaces = {agent: Workspace() for agent in ("parent", "child", "other")}
    manager = SimpleNamespace(
        _repos=repos,
        paths=PathLayout(tmp_path),
        get_agent=lambda aid: SimpleNamespace(workspace=workspaces[aid]),
        _device_service=None,
    )
    yield SimpleNamespace(
        manager=manager,
        repos=repos,
        owner=owner,
        outsider=outsider,
        resources=ResourceService(manager),
        collaboration=CollaborationService(manager),
        workspaces=workspaces,
    )
    pool.close()


def call(rig: Any, identity: str = "inv-1", resources: tuple[str, ...] = (), **changes: Any) -> Any:
    return SimpleNamespace(
        **{
            "user_id": rig.owner,
            "from_agent_id": "parent",
            "to_agent_id": "child",
            "source_thread_id": "root",
            "source_session_key": "root",
            "job_id": None,
            "invocation_id": identity,
            "message": "Read this paper",
            "dispatch_options": Options(resource_ids=resources),
            "retry_of": None,
            **changes,
        }
    )


@pytest.mark.asyncio
async def test_actual_read_tool_does_not_need_device_and_revalidates_source(rig: Any) -> None:
    tool = next(
        tool
        for tool in build_resource_tools(rig.manager, "parent")
        if tool.name == "read_attachment"
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root"}}
    )
    try:
        result = json.loads(await tool.ainvoke({"path": "inbound/paper.txt", "limit": 8}))
        assert result["text"] == "A paper "
        assert result["resource_id"] and result["version"]
        assert result["next_offset"] == 8
        assert result["untrusted_content"] is True
        rig.workspaces["parent"].files["inbound/paper.txt"] = b"Changed source"
        denied = json.loads(await tool.ainvoke({"resource_id": result["resource_id"]}))
        assert denied["status"] == "error"
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_grant_is_exact_invocation_version_and_revocation_checked(rig: Any) -> None:
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    peer = call(rig, resources=(resource["resource_id"],))
    invocation = rig.collaboration.accept(peer)
    invocation.pop("_newly_claimed", None)
    rig.collaboration.bind(peer, "child-thread", {})
    result = await rig.resources.read(
        rig.owner,
        "child",
        "child-thread",
        resource_id=resource["resource_id"],
        invocation_id="inv-1",
    )
    assert result["text"] == "A paper with source text."
    for owner, agent, thread, identity in (
        (rig.owner, "child", "unrelated", "inv-1"),
        (rig.outsider, "other", "foreign", "inv-1"),
        (rig.owner, "child", "child-thread", "forged"),
    ):
        with pytest.raises(OctopError):
            await rig.resources.read(
                owner, agent, thread, resource_id=resource["resource_id"], invocation_id=identity
            )
    with rig.repos.db.transaction() as conn:
        conn.execute("UPDATE collaboration_grants SET revoked=1")
    with pytest.raises(OctopError):
        await rig.resources.read(
            rig.owner,
            "child",
            "child-thread",
            resource_id=resource["resource_id"],
            invocation_id="inv-1",
        )


@pytest.mark.asyncio
async def test_atomic_snapshot_orphan_is_not_advertised_and_retry_reuses_bytes(
    rig: Any, monkeypatch: Any
) -> None:
    save = rig.resources.repo.save
    monkeypatch.setattr(
        rig.resources.repo, "save", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    with pytest.raises(RuntimeError):
        await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    assert rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["artifacts"] == []
    assert list((rig.manager.paths.root / "collaboration" / "resources").rglob("*"))
    monkeypatch.setattr(rig.resources.repo, "save", save)
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    snapshot = rig.resources._snapshot_path(rig.owner, resource["version"])
    assert snapshot.read_bytes() == b"A paper with source text."
    snapshot.unlink()
    with pytest.raises(OctopError):
        await rig.resources.bytes(rig.owner, resource)


@pytest.mark.asyncio
async def test_native_publish_then_delivery_requires_checksum_and_ack(
    rig: Any, monkeypatch: Any
) -> None:
    payload = b"The report generated on GPU."
    digest = hashlib.sha256(payload).hexdigest()
    requests: list[tuple[str, dict[str, Any]]] = []
    context = SimpleNamespace(
        agent_id="parent", thread_id="root", device_id="gpu", target_kind="device"
    )
    mismatch = False

    async def execute(
        owner: int, context_id: str, action: str, params: dict[str, Any], **_: Any
    ) -> dict[str, Any]:
        requests.append((action, params))
        if action == "fs.download.begin":
            result = {"transfer_id": "download", "size": len(payload), "sha256": digest}
        elif action == "fs.download.chunk":
            result = {"data_b64": base64.b64encode(payload).decode()}
        elif action == "fs.upload.begin":
            assert "expected_sha256" not in params
            result = {"transfer_id": "upload"}
        elif action == "fs.upload.chunk":
            result = {"bytes_done": params["offset"] + len(base64.b64decode(params["data_b64"]))}
        elif action == "fs.upload.commit":
            result = {
                "status": "completed",
                "size": len(payload),
                "sha256": "bad" if mismatch else digest,
            }
        else:
            result = {"closed": True}
        return {"result": result}

    monkeypatch.setattr(
        "octop.infra.execution.service.ExecutionService",
        lambda _: SimpleNamespace(get=lambda *a: context, call=execute),
    )
    resource = await rig.resources.publish(rig.owner, "parent", "root", "/project/report.md", "ctx")
    assert resource["source_device_id"] == "gpu"
    assert resource["publication_state"] == "published"
    assert await rig.resources.bytes(rig.owner, resource) == payload
    result = await rig.resources.deliver(
        rig.owner, "parent", "root", resource["resource_id"], "ctx", "/report.md"
    )
    assert result["status"] == "completed"
    mismatch = True
    with pytest.raises(ValueError, match="CHECKSUM"):
        await rig.resources.deliver(
            rig.owner, "parent", "root", resource["resource_id"], "ctx", "/other.md"
        )
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    assert [event["event_type"] for event in events].count("resource.delivered") == 1
    assert events[-1]["event_type"] == "resource.delivery_failed"
    mismatch = False
    retried = await rig.resources.deliver(
        rig.owner, "parent", "root", resource["resource_id"], "ctx", "/retried.md"
    )
    assert retried["status"] == "completed"
    page = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)
    assert page["artifacts"][0]["delivery_status"] == "completed"
    assert "error_code" not in page["artifacts"][0]
    assert page["events"][-1]["event_type"] == "resource.delivered"
    assert "error_code" not in page["events"][-1]["payload"]


def test_schema_upgrade_current_and_already_applied_is_monotonic(rig: Any) -> None:
    invocation = rig.collaboration.accept(call(rig))
    with rig.repos.db.transaction() as conn:
        latest = conn.execute("SELECT version FROM _schema_version").fetchone()[0]
        assert latest >= 29
        conn.execute("UPDATE _schema_version SET version=28")
    run_migrations(rig.repos.db)
    run_migrations(rig.repos.db)
    with rig.repos.db.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == latest
    replay = rig.collaboration.accept(call(rig))
    assert replay["invocation_id"] == invocation["invocation_id"]
    assert not replay.get("_newly_claimed", False)


@pytest.mark.asyncio
async def test_manager_assembled_read_attachment_available_without_device(
    rig: Any, monkeypatch: Any
) -> None:
    from octop.infra.agents.manager import AgentManager

    manager = AgentManager(repos=rig.repos, paths=rig.manager.paths)
    monkeypatch.setattr(manager, "get_agent", rig.manager.get_agent)
    row = rig.repos.agent_repo.get("parent")
    config = manager._build_harness_config(row)
    tools = {tool.name: tool for tool in config.tools}
    assert "read_attachment" in tools
    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    assert "report_task_result" not in tools
    reporting = next(
        item for item in config.middleware if isinstance(item, TaskResultAvailabilityMiddleware)
    )
    assert [tool.name for tool in reporting.tools] == ["report_task_result"]
    assert set(reporting.tools[0].args) == {"outcome", "summary", "resource_ids"}
    assert "read_group_attachment" not in tools
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root"}}
    )
    try:
        result = json.loads(await tools["read_attachment"].ainvoke({"path": "inbound/paper.txt"}))
        assert result["status"] == "ready" and result["resource_id"]
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_parser_cache_survives_service_pages_but_not_grant_validation(
    rig: Any, monkeypatch: Any
) -> None:
    from octop.infra.documents.attachments import AttachmentService

    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    parse = AsyncMock(return_value={"pages": ["123456789"], "parser": "text"})
    monkeypatch.setattr(AttachmentService, "_parse", parse)
    for offset in (0, 3):
        result = await ResourceService(rig.manager).read(
            rig.owner, "parent", "root", resource_id=resource["resource_id"], offset=offset, limit=3
        )
        assert len(result["text"]) == 3
    assert parse.await_count == 1
    rig.workspaces["parent"].files["inbound/paper.txt"] = b"changed"
    with pytest.raises(OctopError):
        await rig.resources.read(rig.owner, "parent", "root", resource_id=resource["resource_id"])
    assert parse.await_count == 1


@pytest.mark.asyncio
async def test_child_gpu_report_parent_reads_then_explicit_laptop_delivery(
    rig: Any, monkeypatch: Any
) -> None:
    payload = b"Verified report from GPU"
    digest = hashlib.sha256(payload).hexdigest()
    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {})
    contexts = {
        "gpu-context": SimpleNamespace(
            context_id="gpu-context",
            agent_id="child",
            thread_id="child-thread",
            device_id="gpu",
            target_kind="device",
        )
    }
    target_bytes = bytearray()

    def resolve(owner, **kwargs):
        assert kwargs["device_id"] == "laptop" and kwargs["work_mode"] == "agentic"
        contexts["laptop-context"] = SimpleNamespace(
            context_id="laptop-context",
            agent_id=kwargs["agent_id"],
            thread_id=kwargs["thread_id"],
            device_id="laptop",
            target_kind="device",
        )
        return contexts["laptop-context"]

    async def execute(owner, context_id, action, params, **kwargs):
        context = contexts[context_id]
        if action == "fs.download.begin":
            assert context.device_id == "gpu"
            result = {"transfer_id": "download", "size": len(payload), "sha256": digest}
        elif action == "fs.download.chunk":
            result = {"data_b64": base64.b64encode(payload).decode()}
        elif action == "fs.upload.begin":
            assert context.device_id == "laptop" and "expected_sha256" not in params
            result = {"transfer_id": "upload"}
        elif action == "fs.upload.chunk":
            target_bytes.extend(base64.b64decode(params["data_b64"]))
            result = {"bytes_done": len(target_bytes)}
        elif action == "fs.upload.commit":
            result = {
                "status": "completed",
                "sha256": hashlib.sha256(target_bytes).hexdigest(),
                "size": len(target_bytes),
            }
        else:
            result = {}
        return {"result": result}

    monkeypatch.setattr(
        "octop.infra.execution.service.ExecutionService",
        lambda _: SimpleNamespace(
            get=lambda owner, identity: contexts[identity], resolve=resolve, call=execute
        ),
    )
    token = var_child_runnable_config.set({"configurable": {"octop_invocation_id": "inv-1"}})
    try:
        resource = await rig.resources.publish(
            rig.owner, "child", "child-thread", "/project/report.md", "gpu-context"
        )
    finally:
        var_child_runnable_config.reset(token)
    assert resource["scope_thread_id"] == "root"
    text = await rig.resources.read(
        rig.owner, "parent", "root", resource_id=resource["resource_id"]
    )
    assert text["text"] == payload.decode()
    with pytest.raises(OctopError):
        await rig.resources.read(
            rig.owner, "child", "unrelated", resource_id=resource["resource_id"]
        )
    result = await rig.resources.deliver(
        rig.owner,
        "parent",
        "root",
        resource["resource_id"],
        None,
        "/reports/report.md",
        device_id="laptop",
        target_kind="device",
    )
    assert result["device_id"] == "laptop" and bytes(target_bytes) == payload
    assert contexts["gpu-context"].device_id == "gpu"


@pytest.mark.asyncio
async def test_same_bytes_publications_have_distinct_thread_references(rig: Any) -> None:
    rig.repos.thread_repo.insert(
        thread_id="root-2",
        agent_id="parent",
        user_id=rig.owner,
        channel_type="dashboard",
        session_key="root-2",
    )
    first = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/report.md",
        thread="root",
        data=b"report",
        source_kind="workspace",
        published=True,
    )
    second = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/report.md",
        thread="root-2",
        data=b"report",
        source_kind="workspace",
        published=True,
    )
    assert first["version"] == second["version"] and first["resource_id"] != second["resource_id"]
    assert len(rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["artifacts"]) == 1
    assert len(rig.collaboration.listing(rig.owner, "parent", "root-2", 0, 100)["artifacts"]) == 1
    assert rig.resources._snapshot_path(
        rig.owner, first["version"]
    ) == rig.resources._snapshot_path(rig.owner, second["version"])


@pytest.mark.asyncio
async def test_same_publication_bytes_on_distinct_devices_keep_provenance(rig: Any) -> None:
    first = await rig.resources.register(
        rig.owner,
        "parent",
        "/report.md",
        thread="root",
        data=b"report",
        source_kind="device",
        source_device_id="gpu",
        source_context_id="gpu-context",
        published=True,
    )
    second = await rig.resources.register(
        rig.owner,
        "parent",
        "/report.md",
        thread="root",
        data=b"report",
        source_kind="device",
        source_device_id="laptop",
        source_context_id="laptop-context",
        published=True,
    )
    assert first["version"] == second["version"] and first["resource_id"] != second["resource_id"]
    assert first["source_device_id"] == "gpu" and second["source_device_id"] == "laptop"


@pytest.mark.asyncio
async def test_boot_binds_canonical_hooks_without_background_processor(
    rig: Any, monkeypatch: Any
) -> None:
    from tests.support.harness import build_harness_manager_mock

    from octop.infra.agents.manager import AgentManager

    manager = AgentManager(repos=rig.repos, paths=rig.manager.paths)
    harness = build_harness_manager_mock()
    monkeypatch.setattr("octop.infra.agents.manager.HarnessAgentManager", lambda **kwargs: harness)
    await manager.boot()
    arguments = harness.team.bind_peer_session.call_args.kwargs
    assert (
        callable(arguments["lifecycle"])
        and callable(arguments["prepare"])
        and callable(arguments["after"])
    )


def test_postgresql_root_lock_precedes_event_sequence_allocation():
    from contextlib import contextmanager

    from octop.infra.db.repos.collaboration import CollaborationRepo

    statements = []

    class Connection:
        rowcount = 1

        def execute(self, sql, params):
            statements.append((sql, params))
            return self

        def fetchone(self):
            return {"thread_id": "root"}

    class Database:
        dialect = "postgresql"

        @contextmanager
        def transaction(self):
            yield Connection()

    repo = CollaborationRepo(Database())
    assert repo.save(
        "collaboration_resources",
        1,
        "resource",
        "root",
        {"version": "digest"},
        "resource.ready",
        event_id="event",
    )
    assert statements[0] == (
        "SELECT thread_id FROM threads WHERE thread_id=? FOR UPDATE",
        ("root",),
    )
    assert (
        next(
            index
            for index, (sql, _) in enumerate(statements)
            if "INSERT INTO collaboration_events" in sql
        )
        > 0
    )


@pytest.mark.asyncio
async def test_startup_marks_missing_corrupt_snapshots_unavailable_without_deletion(
    rig: Any,
) -> None:
    good = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/good.md",
        thread="root",
        data=b"good",
        source_kind="workspace",
        published=True,
    )
    missing = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/missing.md",
        thread="root",
        data=b"missing",
        source_kind="workspace",
        published=True,
    )
    corrupt = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/corrupt.md",
        thread="root",
        data=b"corrupt",
        source_kind="workspace",
        published=True,
    )
    rig.resources._snapshot_path(rig.owner, missing["version"]).unlink()
    corrupt_path = rig.resources._snapshot_path(rig.owner, corrupt["version"])
    corrupt_path.write_bytes(b"incomplete")
    await rig.resources.reconcile_startup()
    await rig.resources.reconcile_startup()
    rows = {
        item["resource_id"]: item
        for item in rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["artifacts"]
    }
    assert rows[good["resource_id"]]["publication_state"] == "published"
    for resource in (missing, corrupt):
        row = rows[resource["resource_id"]]
        assert row["publication_state"] == "unavailable"
        assert (
            row["error_code"] == "RESOURCE_SNAPSHOT_UNAVAILABLE"
            and row["version"] == resource["version"]
        )
        with pytest.raises(OctopError):
            await rig.resources.bytes(rig.owner, resource)
    assert corrupt_path.read_bytes() == b"incomplete"
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    assert len([event for event in events if event["event_type"] == "resource.unavailable"]) == 2


@pytest.mark.asyncio
async def test_snapshot_recovers_same_version_and_repeated_transitions_emit_events(
    rig: Any,
) -> None:
    resource = await rig.resources.register(
        rig.owner,
        "parent",
        "generated/report.md",
        thread="root",
        data=b"report",
        source_kind="workspace",
        published=True,
    )
    path = rig.resources._snapshot_path(rig.owner, resource["version"])
    for _ in range(2):
        path.unlink()
        await rig.resources.reconcile_startup()
        await rig.resources.reconcile_startup()
        unavailable = rig.resources.repo.get(
            "collaboration_resources", rig.owner, resource["resource_id"]
        )
        assert unavailable["publication_state"] == "unavailable"
        path.write_bytes(b"report")
        await rig.resources.reconcile_startup()
        await rig.resources.reconcile_startup()
        restored = rig.resources.repo.get(
            "collaboration_resources", rig.owner, resource["resource_id"]
        )
        assert (
            restored["publication_state"] == "published"
            and restored["version"] == resource["version"]
        )
        assert restored["source_agent_id"] == resource["source_agent_id"]
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    assert [event["event_type"] for event in events].count("resource.unavailable") == 2
    assert [event["event_type"] for event in events].count("resource.ready") == 2


@pytest.mark.asyncio
async def test_latest_snapshot_and_event_references_survive_over_500_records(rig: Any) -> None:
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    first = rig.collaboration.accept(call(rig, identity="old-inv"))
    for index in range(501):
        rig.collaboration.accept(call(rig, identity=f"inv-{index}"))
        artifact = {**resource, "resource_id": f"resource-{index}"}
        rig.resources.repo.save(
            "collaboration_resources",
            rig.owner,
            artifact["resource_id"],
            "root",
            artifact,
            "resource.registered",
            event_id=f"resource-event-{index}",
            resource_id=artifact["resource_id"],
        )
    latest = rig.collaboration.listing(rig.owner, "parent", "root", 10**9, 100)
    assert len(latest["invocations"]) == 500 and len(latest["artifacts"]) == 500
    assert "inv-500" in {row["invocation_id"] for row in latest["invocations"]}
    assert "resource-500" in {row["resource_id"] for row in latest["artifacts"]}
    earlier = rig.collaboration.listing(rig.owner, "parent", "root", 0, 2)
    assert first["invocation_id"] in {row["invocation_id"] for row in earlier["invocations"]}
    assert resource["resource_id"] in {row["resource_id"] for row in earlier["artifacts"]}
    assert len({row["invocation_id"] for row in earlier["invocations"]}) == len(
        earlier["invocations"]
    )
    assert (
        rig.resources.repo.references(
            "collaboration_resources", rig.owner, "unrelated", [resource["resource_id"]]
        )
        == []
    )
    assert (
        rig.resources.repo.references(
            "collaboration_invocations", rig.outsider, "root", [first["invocation_id"]]
        )
        == []
    )


@pytest.mark.asyncio
async def test_registration_honors_configured_resource_cap(rig: Any) -> None:
    from octop.config import OctopConfig
    from octop.infra.errors import ErrorCode

    rig.manager.octop_config = OctopConfig(max_upload_mb=1)
    resources = ResourceService(rig.manager)
    with pytest.raises(OctopError) as captured:
        await resources.register(
            rig.owner,
            "parent",
            "generated/large.bin",
            thread="root",
            data=b"b" * (1024 * 1024 + 1),
            source_kind="workspace",
            published=True,
        )
    assert captured.value.code == ErrorCode.ATTACHMENT_TOO_LARGE
    assert rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["artifacts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["running", "start", "terminal"])
async def test_delivery_conflicts_do_not_report_completed_or_repeat_target_writes(
    rig: Any, monkeypatch: Any, conflict: str
) -> None:
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    context = SimpleNamespace(
        agent_id="parent", thread_id="root", device_id="gpu", target_kind="device"
    )
    actions: list[str] = []
    payload = await rig.resources.bytes(rig.owner, resource)

    async def execute(
        owner: int, context_id: str, action: str, params: dict[str, Any], **_: Any
    ) -> dict[str, Any]:
        actions.append(action)
        result: dict[str, Any] = {}
        if action == "fs.upload.begin":
            result = {"transfer_id": "upload"}
        elif action == "fs.upload.chunk":
            result = {"bytes_done": len(payload)}
        elif action == "fs.upload.commit":
            result = {"status": "completed", "size": len(payload), "sha256": resource["version"]}
        return {"result": result}

    monkeypatch.setattr(
        "octop.infra.execution.service.ExecutionService",
        lambda _: SimpleNamespace(get=lambda *a: context, call=execute),
    )
    original_save = rig.resources.repo.save
    if conflict == "running":
        assert original_save(
            "collaboration_resources",
            rig.owner,
            resource["resource_id"],
            "root",
            {**resource, "delivery_status": "running", "delivery_attempt_id": "other"},
            "resource.delivery_started",
            event_id="other-start",
            resource_id=resource["resource_id"],
            previous=resource,
        )
    else:

        def save(*args: Any, **kwargs: Any) -> bool:
            if args[5] == (
                "resource.delivery_started" if conflict == "start" else "resource.delivered"
            ):
                return False
            return original_save(*args, **kwargs)

        monkeypatch.setattr(rig.resources.repo, "save", save)

    code = (
        "RESOURCE_DELIVERY_RECEIPT_CONFLICT"
        if conflict == "terminal"
        else "RESOURCE_DELIVERY_CONFLICT"
    )
    with pytest.raises(ValueError, match=code):
        await rig.resources.deliver(
            rig.owner, "parent", "root", resource["resource_id"], "ctx", "/report.txt"
        )
    if conflict == "terminal":
        assert actions.count("fs.upload.commit") == 1
        assert (
            rig.resources.repo.get("collaboration_resources", rig.owner, resource["resource_id"])[
                "delivery_status"
            ]
            == "running"
        )
    else:
        assert actions == []
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    assert not any(
        event["event_type"] in {"resource.delivered", "resource.delivery_failed"}
        for event in events
    )
