"""Reopening authorized bytes preserves version identity across transient contexts."""

import base64
import hashlib
from dataclasses import replace
from typing import Any

import pytest
from tests.unit.agents.test_collaboration_resources import rig as workbench_rig

from octop.infra.db.repos.execution import ExecutionContext
from octop.infra.documents.file_sources import FileSourceService
from octop.infra.errors import ErrorCode, OctopError

rig = workbench_rig


class Execution:
    def __init__(self, owner: int) -> None:
        self.context = ExecutionContext(
            "first",
            owner,
            None,
            "/samples",
            1,
            1,
            "agentic",
            "dashboard",
            "local",
            "parent",
            "root",
        )
        self.content = b"Report title"
        self.denied = False
        self.calls: list[str] = []

    def get(self, owner: int, identity: str) -> ExecutionContext:
        assert owner == self.context.owner_user_id and identity == self.context.context_id
        return self.context

    async def call(self, owner: int, identity: str, action: str, params: Any) -> Any:
        self.get(owner, identity)
        self.calls.append(action)
        if self.denied:
            raise OctopError(ErrorCode.FORBIDDEN, "Read revoked")
        if action == "fs.download.begin":
            return {
                "result": {
                    "transfer_id": "transfer",
                    "path": "/samples/report.txt",
                    "size": len(self.content),
                    "sha256": hashlib.sha256(self.content).hexdigest(),
                }
            }
        if action == "fs.download.chunk":
            return {
                "result": {
                    "data_b64": base64.b64encode(self.content).decode(),
                    "offset": 0,
                    "size": len(self.content),
                    "eof": True,
                }
            }
        assert action == "fs.download.close"
        return {"result": {}}


@pytest.mark.asyncio
async def test_reopen_identity_uses_authorized_target_path_version_and_policy(rig: Any) -> None:
    service = FileSourceService(rig.manager)
    execution = Execution(rig.owner)
    service.execution = execution  # type: ignore[assignment]

    async def opened() -> Any:
        return (
            await service.open(
                rig.owner,
                "parent",
                "root",
                {
                    "kind": "execution",
                    "context_id": execution.context.context_id,
                    "path": "report.txt",
                },
            )
        )["resource"]

    first = await opened()
    execution.context = replace(execution.context, context_id="reopened")
    again = await opened()
    assert first["resource_id"] == again["resource_id"]
    stored = rig.resources.repo.get("collaboration_resources", rig.owner, first["resource_id"])
    assert stored["source_context_id"] == "reopened"
    assert stored["source_path"] == "/samples/report.txt"

    execution.context = replace(execution.context, context_id="denied")
    execution.denied = True
    with pytest.raises(OctopError):
        await opened()
    assert (
        rig.resources.repo.get("collaboration_resources", rig.owner, first["resource_id"])[
            "source_context_id"
        ]
        == "reopened"
    )
    execution.denied = False

    execution.context = replace(execution.context, context_id="policy", policy_revision=2)
    changed_policy = await opened()
    assert changed_policy["resource_id"] != first["resource_id"]
    execution.context = replace(
        execution.context, context_id="device", target_kind="device", device_id="different"
    )
    assert (await opened())["resource_id"] != changed_policy["resource_id"]
    execution.content = b"Changed report"
    assert (await opened())["version"] != first["version"]


@pytest.mark.asyncio
async def test_reopen_does_not_revive_an_explicitly_revoked_version(rig: Any) -> None:
    service = FileSourceService(rig.manager)
    execution = Execution(rig.owner)
    service.execution = execution  # type: ignore[assignment]
    source = {"kind": "execution", "context_id": "first", "path": "report.txt"}
    first = (await service.open(rig.owner, "parent", "root", source))["resource"]
    previous = rig.resources.repo.get("collaboration_resources", rig.owner, first["resource_id"])
    rig.resources.repo.save(
        "collaboration_resources",
        rig.owner,
        first["resource_id"],
        "root",
        {**previous, "revoked": True},
        "resource.revoked",
        event_id="test-revoke",
        previous=previous,
    )
    execution.context = replace(execution.context, context_id="reopened")
    with pytest.raises(OctopError):
        await service.open(rig.owner, "parent", "root", {**source, "context_id": "reopened"})
