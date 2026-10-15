"""Adapt the public browser_use schema to the selected device's browser."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.execution.service import ExecutionService


async def browser_tool(
    executions: ExecutionService, owner: int, context_id: str, agent_id: str, args: dict[str, Any]
) -> str | list[str | dict[Any, Any]]:
    original = str(args.get("action") or "")
    action = {
        "goto": "navigate",
        "snapshot": "screenshot",
        "start": "list_tabs",
        "scroll_up": "scroll",
        "scroll_down": "scroll",
    }.get(original, original)

    async def call(operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        value = await executions.call(
            owner, context_id, operation, params or {}, actor_agent_id=agent_id
        )
        return dict(value["result"])

    if action == "close_session":
        result = await call("browser.close")
    else:
        await call("browser.open")
        if action == "list_tabs":
            result = await call("browser.state")
        elif action == "dom_tree":
            result = await call("browser.observe")
        elif action == "screenshot":
            if args.get("full_page") or args.get("crop") or args.get("path"):
                raise ValueError(
                    "device screenshots return a bounded viewport image; full_page, crop and output path are unsupported"
                )
            result = await call("browser.capture")
            image = result.pop("data_b64")
            return [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{result['mime']};base64,{image}"},
                },
                {
                    "type": "text",
                    "text": json.dumps(
                        {"success": True, "action": action, "content": result}, ensure_ascii=False
                    ),
                },
            ]
        else:
            params = {
                key: value
                for key, value in args.items()
                if key in {"ref", "selector", "text", "expression", "tab_id", "amount", "direction"}
                and value not in ("", None)
            }
            if action in {"navigate", "new_tab"}:
                params["url"] = next(
                    (
                        str(args[key]).strip()
                        for key in ("url", "target_url", "href", "query", "link", "address")
                        if args.get(key)
                    ),
                    "about:blank" if action == "new_tab" else "",
                )
            if original in {"scroll_up", "scroll_down"}:
                params["direction"] = "up" if original == "scroll_up" else "down"
            result = await call("browser.action", {**params, "command": action})
    return json.dumps(
        {"tool": "browser_use", "action": action, "success": True, "content": result},
        ensure_ascii=False,
    )
