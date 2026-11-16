"""The in-process MCP gateway preserves server schemas and explicit nulls."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from octop.infra.connectors.catalog import get_catalog_entry
from octop.infra.connectors.gateway import langchain


def test_gateway_preserves_complex_arguments_and_nullable_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {
        "type": "object",
        "properties": {
            "_client_info": {"type": "object", "properties": {"id": {"type": "integer"}}},
            "items": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
            "schema": {"type": ["string", "null"]},
            "optional": {"type": "integer"},
        },
        "required": ["_client_info", "items", "schema"],
        "additionalProperties": False,
    }
    monkeypatch.setattr(
        langchain,
        "mcp_tools_for_kind",
        lambda _: [{"name": "write", "description": "Write", "inputSchema": schema}],
    )
    received: list[dict[str, Any]] = []

    def handle(**kwargs: Any) -> dict[str, Any]:
        arguments = kwargs["body"]["params"]["arguments"]
        received.append(arguments)
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}

    monkeypatch.setattr(langchain, "handle_mcp_request", handle)
    entry = get_catalog_entry("tencent-news")
    assert entry is not None
    tool = langchain.build_gateway_langchain_tools(
        entry=entry, instance_id="instance", mcp_server_name="gateway", creds={}
    )[0]
    assert tool.args_schema == schema
    binding = convert_to_openai_tool(tool)["function"]["parameters"]
    assert binding["properties"]["_client_info"]["type"] == "object"
    assert binding["properties"]["items"]["items"]["enum"] == ["a", "b"]
    arguments = {"_client_info": {"id": 1}, "items": ["a"], "schema": None}
    assert tool.invoke(arguments) == "ok"
    assert tool.invoke({**arguments, "optional": None}) == "ok"
    assert received == [arguments, arguments]
