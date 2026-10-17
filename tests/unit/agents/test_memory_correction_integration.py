"""Host policy and the actually installed harness must expose memory maintenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from octop_harness.builtin.tools.memory_tools import build_memory_tools
from octop_harness.memory.management import _ManagedMemoryService
from octop_memory import Memory

from octop.i18n import hitl_tool_catalog, tool_display_name
from octop.infra.agents.settings.tool_catalog import (
    BUILTIN_TOOL_CATALOG,
    builtin_tool_available,
    effective_tools_disabled,
)
from octop.infra.agents.teams.service import HOST_TOOLS_DISABLED

NAMES = {"memory_list", "memory_write", "memory_update", "memory_delete"}


@pytest.mark.parametrize("name", sorted(NAMES))
def test_memory_maintenance_obeys_host_catalog_availability_and_policy(name: str) -> None:
    assert any(entry.name == name and entry.category == "memory" for entry in BUILTIN_TOOL_CATALOG)
    assert builtin_tool_available(name, agent_cfg={})
    assert not builtin_tool_available(name, agent_cfg={"memory": {"memory_enabled": False}})
    assert name in effective_tools_disabled({"tools_disabled": [name]})
    assert name in HOST_TOOLS_DISABLED  # Team hosts retain their existing read-only memory policy.
    assert tool_display_name(name, "zh") != name
    assert tool_display_name(name, "en") != name


def test_memory_writes_remain_selectable_for_host_approval() -> None:
    names = {entry.name for entry in hitl_tool_catalog()}
    assert {"memory_write", "memory_update", "memory_delete"} <= names
    assert "memory_list" not in names


def test_installed_harness_corrects_an_obsolete_fact(tmp_path: Path) -> None:
    memory = Memory(
        namespace="agent_fixture", backend_config={"db_path": str(tmp_path / "memory.sqlite")}
    )
    try:
        service = _ManagedMemoryService(memory)
        tools = {tool.name: tool for tool in build_memory_tools(service)}
        assert tools.keys() >= NAMES
        created = json.loads(
            tools["memory_write"].invoke(
                {
                    "content": "GPU MEMORY.md permission denied",
                    "topic": "GPU",
                    "reason": "old observation",
                }
            )
        )
        corrected = json.loads(
            tools["memory_update"].invoke(
                {
                    "path": created["path"],
                    "expected_content": created["content"],
                    "content": "Since 2026-10-17 GPU MEMORY.md read/edit/readback is verified",
                    "reason": "verified controller storage fix",
                }
            )
        )
        assert corrected["status"] == "replaced"
        readback = tools["memory_get"].invoke({"path": corrected["path"]})
        assert corrected["content"] in readback and "permission denied" not in readback
        result = tools["memory_search"].invoke({"query": "MEMORY.md"})
        assert "permission denied" not in result
        assert corrected["path"] in result
    finally:
        memory.backend.close()
