"""MCP / connector execution location authorization (0038 F01).

Ordinary accounts must not spawn stdio MCP processes on the control server.
Rules live here; HTTP routers and loaders only call these helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from octop.infra.errors import ErrorCode, OctopError

ExecutionLocation = Literal["control_server", "user_device"]

_STDIO_DENIED_MSG = (
    "stdio MCP cannot run on the control server for non-admin accounts; "
    "bind a user device or use streamable_http, or ask an admin for local MCP"
)


def mcp_transport_of(spec: dict[str, Any] | None) -> str:
    """Return normalized transport name from a custom MCP server spec."""
    if not isinstance(spec, dict):
        return ""
    transport = str(spec.get("transport") or "").strip().lower()
    if transport == "http":
        return "streamable_http"
    return transport


def actor_is_admin(actor: Any) -> bool:
    """True when *actor* is an admin user (object with ``is_admin`` / ``role``)."""
    if actor is None:
        return False
    if bool(getattr(actor, "is_admin", False)):
        return True
    role = getattr(actor, "role", None)
    if isinstance(role, str) and role.strip().lower() == "admin":
        return True
    return False


def authorize_mcp_execution(
    actor: Any,
    *,
    transport: str,
    location: ExecutionLocation = "control_server",
) -> None:
    """Allow or deny MCP process/network start for *actor* at *location*.

    Raises ``OctopError`` with ``FORBIDDEN`` before any subprocess is spawned.
    """
    normalized = (transport or "").strip().lower()
    if normalized == "http":
        normalized = "streamable_http"
    if normalized != "stdio":
        return
    if location != "control_server":
        return
    if actor_is_admin(actor):
        return
    raise OctopError(ErrorCode.FORBIDDEN, _STDIO_DENIED_MSG)


def authorize_stdio_mcp_spec(
    actor: Any,
    spec: dict[str, Any] | None,
    *,
    location: ExecutionLocation = "control_server",
) -> None:
    """Authorize one custom MCP server spec (no-op for non-stdio)."""
    authorize_mcp_execution(
        actor,
        transport=mcp_transport_of(spec),
        location=location,
    )
