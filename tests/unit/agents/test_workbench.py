"""Real persistence validates file version comments, plans and modification authority."""

from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.agents.test_collaboration_resources import rig as workbench_rig

from octop.infra.documents.annotations import Anchor, AnnotationService
from octop.infra.documents.file_sources import byte_range
from octop.infra.documents.resources import ResourceService
from octop.infra.errors import OctopError
from octop.infra.execution.activity import ActivityService, WorkPlan

rig = workbench_rig


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_name", [None, r"D:\samples\notes.md"])
async def test_windows_snapshot_reads_use_parser_basename(
    rig: Any, historical_name: str | None
) -> None:
    resources = ResourceService(rig.manager)
    resource = await resources.register(
        rig.owner,
        "parent",
        r"D:\samples\notes.md",
        thread="root",
        data=b"# Snapshot title\n",
        source_kind="workspace",
        name=historical_name,
    )
    if historical_name is None:
        assert resource["name"] == "notes.md"
    result = await resources.read(rig.owner, "parent", "root", resource_id=resource["resource_id"])
    assert result["status"] == "ready"
    assert result["text"] == "# Snapshot title\n"


def test_ranges() -> None:
    assert byte_range("bytes=4-9", 8) == (4, 7)
    assert byte_range("bytes=-3", 8) == (5, 7)
    assert byte_range("bytes=3-", 8) == (3, 7)
    assert byte_range("bytes=8-", 8) is None
    assert byte_range("bytes=0-0,2-3", 8) is None
    assert byte_range("bytes=-0", 8) is None


def test_anchor_validation() -> None:
    for anchor in [
        {"kind": "image", "rect": [0.9, 0, 0.2, 1]},
        {"kind": "time", "start": float("inf"), "end": float("inf")},
        {"kind": "text", "line": 3, "column": 2, "end_line": 1, "end_column": 2},
        {"kind": "sheet", "sheet": "Sheet1", "cells": "A0"},
        {"kind": "document"},
    ]:
        with pytest.raises(ValidationError):
            Anchor.model_validate(anchor)


def test_plan_dependencies_and_revision(rig: Any) -> None:
    service = ActivityService(rig.manager)
    body = {
        "plan_id": "one",
        "revision": 0,
        "tasks": [
            {"task_id": "A", "title": "Read"},
            {"task_id": "B", "title": "Disk", "depends_on": ["A"]},
            {"task_id": "C", "title": "Logs", "depends_on": ["A"]},
            {"task_id": "D", "title": "Report", "depends_on": ["B", "C"]},
        ],
    }
    result = service.plan(rig.owner, "parent", "root", "run", WorkPlan.model_validate(body))
    assert result["revision"] == 1
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        service.plan(rig.owner, "parent", "root", "run", WorkPlan.model_validate(body))
    with pytest.raises(ValueError, match="ALREADY_DECLARED"):
        service.plan(
            rig.owner, "parent", "root", "run", WorkPlan.model_validate({**body, "plan_id": "two"})
        )
    with pytest.raises(ValidationError):
        WorkPlan.model_validate(
            {**body, "tasks": [{"task_id": "A", "title": "Self", "depends_on": ["A"]}]}
        )


@pytest.mark.asyncio
async def test_comment_version_revision_scope_and_request_idempotency(rig: Any) -> None:
    resources = ResourceService(rig.manager)
    resource = await resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    service = AnnotationService(rig.manager)
    comment = service.create(
        rig.owner,
        "parent",
        "root",
        resource["resource_id"],
        resource["version"],
        Anchor(kind="text", line=1, column=1, end_line=1, end_column=4, quote="A p"),
        "Improve title",
    )
    assert (
        service.listing(rig.owner, "parent", "root", resource["resource_id"], 0, 5)["items"][0][
            "body"
        ]
        == "Improve title"
    )
    updated = service.update(
        rig.owner,
        "parent",
        "root",
        resource["resource_id"],
        comment["annotation_id"],
        1,
        None,
        None,
        "More detail",
    )
    assert updated["revision"] == 2
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        service.update(
            rig.owner,
            "parent",
            "root",
            resource["resource_id"],
            comment["annotation_id"],
            1,
            None,
            "resolved",
            None,
        )
    body = {
        "command_id": "command1",
        "resource_id": resource["resource_id"],
        "source_version": resource["version"],
        "annotations": [{"annotation_id": comment["annotation_id"], "revision": 2}],
    }
    first = service.prepare_request(rig.owner, "parent", "root", body)
    assert first == service.prepare_request(rig.owner, "parent", "root", body)
    with pytest.raises(ValueError, match="COMMAND_CONFLICT"):
        service.prepare_request(
            rig.owner,
            "parent",
            "root",
            {**body, "annotations": [{"annotation_id": comment["annotation_id"], "revision": 1}]},
        )
    with pytest.raises(OctopError):
        service.listing(rig.outsider, "parent", "root", resource["resource_id"], 0, 10)
    with pytest.raises(OctopError):
        await resources.publish(
            rig.owner,
            "parent",
            "root",
            "generated/new.txt",
            modification_request_id=first["request_id"],
            run_id="unrelated-run",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("http_ack_first", [False, True])
async def test_queue_dispatch_can_publish_before_http_ack(rig: Any, http_ack_first: bool) -> None:
    resources = ResourceService(rig.manager)
    resource = await resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    service = AnnotationService(rig.manager)
    comment = service.create(
        rig.owner,
        "parent",
        "root",
        resource["resource_id"],
        resource["version"],
        Anchor(kind="file"),
        "Revise title",
    )
    request = service.prepare_request(
        rig.owner,
        "parent",
        "root",
        {
            "command_id": "fast-command",
            "resource_id": resource["resource_id"],
            "source_version": resource["version"],
            "annotations": [{"annotation_id": comment["annotation_id"], "revision": 1}],
        },
    )
    with pytest.raises(ValueError, match="QUEUE_ADMISSION_REQUIRED"):
        service.bind_run(rig.owner, "parent", "root", request["request_id"], "real-run")
    receipt = rig.repos.chat_input_repo.create(
        rig.owner,
        "parent",
        "root",
        "fast-command",
        kind="chat_input",
        run_id="",
        payload={"snapshot": {"modification_request_id": request["request_id"]}},
        status="queued",
    )
    if http_ack_first:
        service.queued(rig.owner, request, receipt)
    assert rig.repos.chat_input_repo.transition(rig.owner, "fast-command", "queued", "dispatching")
    bound = service.bind_run(rig.owner, "parent", "root", request["request_id"], "real-run")
    assert bound["run_id"] == "real-run"
    with pytest.raises(ValueError, match="ALREADY_BOUND"):
        service.bind_run(rig.owner, "parent", "root", request["request_id"], "forged-run")
    rig.workspaces["parent"].files["generated/revised.txt"] = b"Revised title."
    result = await resources.publish(
        rig.owner,
        "parent",
        "root",
        "generated/revised.txt",
        modification_request_id=request["request_id"],
        run_id="real-run",
    )
    acknowledged = service.queued(rig.owner, request, receipt)
    assert acknowledged["state"] == "result_available"
    assert acknowledged["run_id"] == "real-run"
    assert acknowledged["results"] == [
        {"resource_id": result["resource_id"], "version": result["version"]}
    ]
    assert (
        service.listing(rig.owner, "parent", "root", resource["resource_id"], 0, 5)["items"][0][
            "status"
        ]
        == "open"
    )


@pytest.mark.asyncio
async def test_resource_range_reads_only_requested_bytes(rig: Any, monkeypatch: Any) -> None:
    resource = await rig.resources.register(
        rig.owner,
        "parent",
        "large.bin",
        thread="root",
        source_kind="workspace",
        data=b"a" * (2 * 1024 * 1024),
    )

    def forbid_full_read(*args: Any) -> bytes:
        raise AssertionError("range must not read the complete snapshot")

    monkeypatch.setattr(rig.resources, "_read_snapshot", forbid_full_read)
    chunks = [
        chunk async for chunk in rig.resources.content_chunks(rig.owner, resource, 1000000, 1001023)
    ]
    assert chunks == [b"a" * 1024]
    full = [
        chunk
        async for chunk in rig.resources.content_chunks(
            rig.owner, resource, 0, resource["size"] - 1
        )
    ]
    assert sum(map(len, full)) == resource["size"]
    assert max(map(len, full)) == 65536


def test_activity_real_dependencies_and_recent_job_survive_parent_exit(rig: Any) -> None:
    from octop.infra.db.repos.run_events import RunEventRepo

    rig.manager.steering_status = lambda agent, thread: None
    service = ActivityService(rig.manager)
    service.plan(
        rig.owner,
        "parent",
        "root",
        "ended-parent",
        WorkPlan.model_validate(
            {
                "plan_id": "fork",
                "revision": 0,
                "tasks": [
                    {"task_id": "A", "title": "Read", "status": "completed"},
                    {"task_id": "B", "title": "Process", "depends_on": ["A"]},
                ],
            }
        ),
    )
    first = service.snapshot(rig.owner, "parent", "root")
    assert next(n for n in first["nodes"] if n.get("task_id") == "B")["status"] == "waiting"
    events = RunEventRepo(rig.repos.db)
    events.save(
        event_id="dispatch:A",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id="ended-parent",
        context_id=None,
        kind="dispatch",
        status="completed",
        payload={"task_id": "A"},
    )
    events.save(
        event_id="job:detached",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id="ended-parent",
        context_id=None,
        kind="job",
        status="running",
        payload={"job_id": "real-job", "observation": {"status": "current"}},
    )
    result = service.snapshot(rig.owner, "parent", "root")
    assert next(n for n in result["nodes"] if n.get("task_id") == "B")["status"] == "pending"
    job = next(n for n in result["nodes"] if n["id"] == "job:detached")
    assert job["observed_status"] == "current" and result["counts"]["jobs"] == 1
    events.save(
        event_id="job:detached",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id="ended-parent",
        context_id=None,
        kind="job",
        status="running",
        payload={"job_id": "real-job", "observation": {"status": "unavailable"}},
    )
    assert service.snapshot(rig.owner, "parent", "root")["counts"]["jobs"] == 0


def test_activity_bounded_window_has_reachable_history(rig: Any) -> None:
    from octop.infra.db.repos.run_events import RunEventRepo

    rig.manager.steering_status = lambda agent, thread: None
    events = RunEventRepo(rig.repos.db)
    for i in range(205):
        events.save(
            event_id=f"tool:{i}",
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id="run",
            context_id=None,
            kind="tool",
            status="completed",
            payload={"name": f"Tool {i}"},
        )
    service = ActivityService(rig.manager)
    page = service.snapshot(rig.owner, "parent", "root")
    assert len(page["nodes"]) == 200 and page["scope_truncated"] and page["next_before"]
    older = service.snapshot(rig.owner, "parent", "root", page["next_before"])
    assert len(older["nodes"]) == 5 and not older["scope_truncated"]
    assert len({n["id"] for n in page["nodes"] + older["nodes"]}) == 205


def test_old_active_job_is_not_lost_outside_recent_history_window(rig: Any) -> None:
    from octop.infra.db.repos.run_events import RunEventRepo

    rig.manager.steering_status = lambda agent, thread: None
    events = RunEventRepo(rig.repos.db)
    events.save(
        event_id="job:old-active",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id="old-run",
        context_id=None,
        kind="job",
        status="running",
        payload={"job_id": "old-job"},
    )
    for i in range(205):
        events.save(
            event_id=f"recent:{i}",
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id="run",
            context_id=None,
            kind="tool",
            status="completed",
            payload={},
        )
    snapshot = ActivityService(rig.manager).snapshot(rig.owner, "parent", "root")
    assert snapshot["counts"]["jobs"] == 1
    assert any(n["id"] == "job:old-active" for n in snapshot["nodes"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "changed", "missing"])
async def test_upload_alias_validated_before_request_or_queue(
    rig: Any, monkeypatch: Any, change: str
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from octop.api.routers.chat import annotations as route

    resource = await rig.resources.register(
        rig.owner, "parent", "inbound/paper.txt", thread="root", source_kind="upload"
    )
    service = AnnotationService(rig.manager)
    comment = service.create(
        rig.owner,
        "parent",
        "root",
        resource["resource_id"],
        resource["version"],
        Anchor(kind="file"),
        "Revise",
    )
    body = route.ModificationBody.model_validate(
        {
            "command_id": "upload-command",
            "resource_id": resource["resource_id"],
            "source_version": resource["version"],
            "annotations": [{"annotation_id": comment["annotation_id"], "revision": 1}],
        }
    )
    queue = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(route, "queue_input", queue)
    if change == "changed":
        rig.workspaces["parent"].files["inbound/paper.txt"] = b"B paper with source text."
    elif change == "missing":
        del rig.workspaces["parent"].files["inbound/paper.txt"]
    server = SimpleNamespace(app_runtime=SimpleNamespace(agent_registry=rig.manager))
    if change == "unchanged":
        value = await route.request_modification(
            "parent", "root", body, SimpleNamespace(id=rig.owner), server
        )
        assert value["state"] == "queued"
        queue.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as exc:
            await route.request_modification(
                "parent", "root", body, SimpleNamespace(id=rig.owner), server
            )
        assert exc.value.status_code == 409
        assert exc.value.detail == "ANNOTATION_SOURCE_CONFLICT"
        queue.assert_not_awaited()
        assert service.requests(rig.owner, "parent", "root", resource["resource_id"]) == []
