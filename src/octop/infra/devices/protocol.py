"""Device wire limits and capability rules shared by the control center."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.errors import ErrorCode, OctopError

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
# Wire protocol: v1 = legacy reduce-only clients; v2 = grant proposals / expand.
DEVICE_PROTOCOL_VERSION = 1
CLIENT_PROTOCOL_VERSION = 2
PENDING_GRANT_TTL_SECONDS = 72 * 3600


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
