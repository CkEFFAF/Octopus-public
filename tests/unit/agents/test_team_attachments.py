from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.infra.agents.teams.attachments import build_room_attachment_tool


@pytest.mark.asyncio
async def test_room_attachment_read_and_pagination() -> None:
    workspace = SimpleNamespace(adownload_bytes=AsyncMock(return_value="群聊附件验收".encode()))
    tool = build_room_attachment_tool(workspace, locale="zh")
    first = json.loads(await tool.ainvoke({"path": "/inbound/qa.txt", "limit": 3}))
    assert first["text"] == "群聊附"
    assert first["next_offset"] == 3
    second = json.loads(await tool.ainvoke({"path": "inbound/qa.txt", "offset": 3}))
    assert second["text"] == "件验收"
    assert second["next_offset"] is None
    workspace.adownload_bytes.assert_awaited_with("inbound/qa.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "SOUL.md",
        "inbound/../SOUL.md",
        "/etc/passwd",
        "inbound/..",
        "inbound/a\\b",
        "inbound/C:secret",
    ],
)
async def test_room_attachment_cannot_read_other_files(path: str) -> None:
    workspace = SimpleNamespace(adownload_bytes=AsyncMock())
    result = json.loads(await build_room_attachment_tool(workspace).ainvoke({"path": path}))
    assert result["error"]
    workspace.adownload_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_room_attachment_missing_binary_and_oversized_are_explicit_errors() -> None:
    for content in (None, b"\x00binary", b"a" * (8 * 1024 * 1024 + 1)):
        workspace = SimpleNamespace(adownload_bytes=AsyncMock(return_value=content))
        result = json.loads(
            await build_room_attachment_tool(workspace).ainvoke({"path": "inbound/qa.txt"})
        )
        assert result["error"]
