"""User-scoped MCP tool cache helpers (fingerprint + serialized tool wrappers)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from langchain_core.tools import StructuredTool

from octop.infra.metrics import PERFORMANCE


@dataclass
class _InvocationGate:
    limit: int
    active: int = 0
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[None]:
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1
        try:
            yield
        finally:
            async with self.condition:
                self.active -= 1
                self.condition.notify_all()


_GATES: WeakKeyDictionary[asyncio.Lock, _InvocationGate] = WeakKeyDictionary()

# Connection fields that affect the live MCP session (exclude Octop meta like enabled).
_FINGERPRINT_KEYS = (
    "transport",
    "url",
    "headers",
    "command",
    "args",
    "env",
)


def fingerprint_mcp_spec(spec: dict[str, Any]) -> str:
    """Stable short hash of a harness MCP connection spec."""
    payload: dict[str, Any] = {}
    for key in _FINGERPRINT_KEYS:
        if key not in spec:
            continue
        value = spec[key]
        if key in ("headers", "env") and isinstance(value, dict):
            payload[key] = {str(k): str(v) for k, v in sorted(value.items())}
        elif key == "args" and isinstance(value, list):
            payload[key] = [str(x) for x in value]
        else:
            payload[key] = value
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def wrap_tools_for_shared_use(
    tools: list[Any],
    lock: asyncio.Lock,
    *,
    check_access: Callable[[], None] | None = None,
    max_concurrent_calls: int = 1,
) -> list[Any]:
    """Return LangChain ``StructuredTool`` wrappers that serialize invoke/ainvoke.

    Must be real ``BaseTool`` instances so ``HarnessAgent.append_mcp_tools`` /
    LangGraph ``ToolNode`` accept them (plain proxies raise ValueError).
    """
    from pydantic import BaseModel, create_model

    if type(max_concurrent_calls) is not int or not 1 <= max_concurrent_calls <= 8:
        raise ValueError("max_concurrent_calls must be 1..8")
    gate = _GATES.setdefault(lock, _InvocationGate(max_concurrent_calls))
    # All fingerprints share admission state. A policy reduction also governs
    # queued calls from older wrappers; accepted calls can finish normally.
    gate.limit = max_concurrent_calls

    wrapped: list[Any] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "") or "mcp_tool"
        description = str(getattr(tool, "description", "") or "")
        args_schema = getattr(tool, "args_schema", None)
        metadata = getattr(tool, "metadata", None)
        if not (
            isinstance(args_schema, type)
            and issubclass(args_schema, BaseModel)
            or isinstance(args_schema, dict)
        ):
            args_schema = create_model(f"{name.replace('-', '_')}_Args")

        async def _acall(
            _tool: Any = tool,
            _gate: _InvocationGate = gate,
            _check_access: Callable[[], None] | None = check_access,
            **kwargs: Any,
        ) -> Any:
            started = time.perf_counter()
            async with _gate.lease():
                PERFORMANCE.observe("mcp_wait", time.perf_counter() - started)
                if _check_access is not None:
                    await asyncio.to_thread(_check_access)
                with PERFORMANCE.measure("mcp_call"):
                    return await _tool.ainvoke(kwargs)

        def _call(
            _invoke: Callable[..., Awaitable[Any]] = _acall,
            **kwargs: Any,
        ) -> Any:
            try:
                asyncio.get_running_loop()
            except RuntimeError:

                async def run() -> Any:
                    return await _invoke(**kwargs)

                return asyncio.run(run())
            raise RuntimeError(
                "Use tool.ainvoke inside an active event loop to preserve admission limits"
            )

        st_kwargs: dict[str, Any] = {
            "name": name,
            "description": description,
            "args_schema": args_schema,
            "coroutine": _acall,
            "func": _call,
        }
        if isinstance(metadata, dict) and metadata:
            st_kwargs["metadata"] = dict(metadata)
        wrapped.append(StructuredTool(**st_kwargs))
    return wrapped
