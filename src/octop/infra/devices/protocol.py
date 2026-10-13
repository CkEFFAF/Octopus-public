"""Device wire limits and capability rules shared by the control center."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.errors import OctopError

CAPABILITIES = frozenset(
    {"desktop_view", "desktop_control", "files_read", "files_write", "command_exec", "acp_run"}
)
# REQ-007: enroll defaults when each item is in capabilities.
DEFAULT_ENROLL_PERMISSIONS = frozenset({"desktop_view", "desktop_control", "files_read"})
# DEC-005: these expansions always require device-side confirm.
HIGH_RISK_PERMISSIONS = frozenset({"command_exec", "acp_run"})
REMOTE_GRANT_MODES = frozenset({"confirm", "owner_auto"})
DEFAULT_REMOTE_GRANT_MODE = "owner_auto"
# 0006 DEC-001: product default control-center URL (overridable).
DEFAULT_DEVICE_SERVER = "https://octop.effaf.me"
# Env override key for first-run / join when --server is omitted (0006 AC / DEC-001).
DEVICE_SERVER_ENV = "OCTOP_DEVICE_SERVER"
# 0010 DEC-T05: filing-period hub only — never widen to arbitrary remote HTTP.
TRANSITION_INSECURE_HOST = "111.228.42.228"
TRANSITION_INSECURE_PORT = 8188


def is_transition_insecure_allowed(url: str) -> bool:
    """True only for http://111.228.42.228:8188 (0010 scoped allow-insecure)."""
    import urllib.parse

    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host != TRANSITION_INSECURE_HOST:
        return False
    port = parsed.port if parsed.port is not None else 80
    return port == TRANSITION_INSECURE_PORT


def resolve_default_device_server() -> str:
    """Product default, or OCTOP_DEVICE_SERVER when set and non-empty."""
    import os

    override = os.environ.get(DEVICE_SERVER_ENV, "").strip()
    return override or DEFAULT_DEVICE_SERVER


# Wire protocol: v1 = legacy reduce-only clients; v2 = grant proposals / expand.
DEVICE_PROTOCOL_VERSION = 1
CLIENT_PROTOCOL_VERSION = 2
PENDING_GRANT_TTL_SECONDS = 72 * 3600
# 0008 MVP-S1: controlled-device must confirm desktop target switch (DEC-001).
PENDING_TAKEOVER_TTL_SECONDS = 60
DESKTOP_TAKEOVER_MODES = frozenset({"view", "view_control"})


def default_enroll_permissions(capabilities: list[str] | set[str]) -> list[str]:
    return sorted(DEFAULT_ENROLL_PERMISSIONS & set(capabilities))


def merge_enroll_permissions(
    capabilities: list[str] | set[str], requested: list[str] | set[str]
) -> list[str]:
    """Apply REQ-007 defaults and keep explicit higher grants from the client."""
    caps = set(capabilities)
    return sorted((set(requested) | (DEFAULT_ENROLL_PERMISSIONS & caps)) & caps)


ACTION_PERMISSION = {
    "ping": "",
    "status": "",
    "files.list": "files_read",
    "files.stat": "files_read",
    "files.read": "files_read",
    "files.write_begin": "files_write",
    "files.write_chunk": "files_write",
    "files.write_commit": "files_write",
    "files.write_abort": "files_write",
    "desktop.capture": "desktop_view",
    "desktop.input": "desktop_control",
    "command.run": "command_exec",
    "acp.open": "acp_run",
    "acp.write": "acp_run",
    "acp.poll": "acp_run",
    "acp.close": "acp_run",
}
CHUNK_SIZE = 1024 * 1024
MAX_FRAME = 4 * 1024 * 1024


def device_error(key: str, *, status: int = 400) -> OctopError:
    """Build a DEVICE_INVALID OctopError (server-side; not used by portable client)."""
    from octop.infra.errors import ErrorCode, OctopError

    return OctopError(ErrorCode.DEVICE_INVALID, key, status=status)


def validate_action(action: str, params: dict[str, Any]) -> str:
    if action not in ACTION_PERMISSION:
        raise device_error("unsupported device action")
    if len(json.dumps(params).encode("utf-8")) > 2 * CHUNK_SIZE:
        raise device_error("device request too large")
    if action == "files.read":
        length = params.get("length", CHUNK_SIZE)
        if type(length) is not int or not 1 <= length <= CHUNK_SIZE:
            raise device_error("invalid read length")
    if action == "command.run":
        timeout = params.get("timeout", 60)
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise device_error("invalid command timeout")
    return ACTION_PERMISSION[action]


def ledger_result(action: str, value: dict[str, Any]) -> dict[str, Any]:
    """Keep private desktop frames and file bytes out of the durable ledger."""
    return {k: v for k, v in value.items() if k not in {"jpeg_b64", "data_b64", "session_id"}}


def result_status(action: str, value: dict[str, Any]) -> str:
    if action == "command.run" and value.get("returncode") != 0:
        return "failed"
    return "completed"
