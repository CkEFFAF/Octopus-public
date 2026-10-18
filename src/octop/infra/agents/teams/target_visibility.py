"""0019: expert default target visibility + ask_agent target_policy (inherit|member_default|explicit)."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)

TargetPolicy = Literal["inherit", "member_default", "explicit"]


def expert_default_target(
    *,
    device_binding: dict[str, Any] | None,
    device_name: str | None = None,
) -> dict[str, Any] | None:
    """Readonly summary of an expert's ``device_binding`` (not session/account)."""
    if not isinstance(device_binding, dict):
        return None
    kind = device_binding.get("target_kind") or (
        "device" if device_binding.get("device_id") else None
    )
    if kind == "local":
        return {
            "target_kind": "local",
            "device_id": None,
            "device_name": None,
            "working_dir": device_binding.get("working_dir"),
        }
    device_id = device_binding.get("device_id")
    if not device_id:
        return None
    return {
        "target_kind": "device",
        "device_id": str(device_id),
        "device_name": device_name,
        "working_dir": device_binding.get("working_dir"),
    }


def model_ref_for_row(row: Any) -> str | None:
    raw = getattr(row, "default_model", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def binding_from_row(row: Any) -> dict[str, Any] | None:
    try:
        cfg = json.loads(getattr(row, "config_json", None) or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(cfg, dict):
        return None
    binding = cfg.get("device_binding")
    return binding if isinstance(binding, dict) else None


def visible_expert_defaults(
    row: Any, viewer_user_id: int | None, device_repo: Any
) -> dict[str, Any]:
    """Default execution details belong to the expert owner, including for shared experts."""
    if viewer_user_id is None or getattr(row, "user_id", None) != viewer_user_id:
        return {"default_target": None, "model_ref": None}
    binding = binding_from_row(row)
    device_name = None
    if binding and binding.get("device_id"):
        device = device_repo.get(str(binding["device_id"]))
        if device is not None and device.owner_user_id == viewer_user_id:
            device_name = device.name
    return {
        "default_target": expert_default_target(device_binding=binding, device_name=device_name),
        "model_ref": model_ref_for_row(row),
    }


def _validate_explicit_target(target: dict[str, Any]) -> None:
    device_id = target.get("device_id")
    kind = target.get("target_kind") or ("device" if device_id else None)
    if (
        kind not in {"device", "local"}
        or (kind == "local" and device_id)
        or (kind == "device" and (not isinstance(device_id, str) or not device_id.strip()))
    ):
        raise OctopError(
            ErrorCode.FORBIDDEN, "explicit dispatch requires a device id or local target"
        )
    directory = target.get("working_dir")
    if directory is not None and (not isinstance(directory, str) or "\x00" in directory):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid explicit working directory")


def enrich_peer_metadata(
    metadata: dict[str, Any],
    *,
    row: Any,
    device_name: str | None = None,
) -> None:
    """Attach ``default_target`` / ``model_ref`` for agent_list (AC-06)."""
    metadata["default_target"] = expert_default_target(
        device_binding=binding_from_row(row),
        device_name=device_name,
    )
    metadata["model_ref"] = model_ref_for_row(row)
    metadata["octop_owner_user_id"] = getattr(row, "user_id", None)


def apply_target_policy(
    snapshot: dict[str, Any],
    *,
    policy: str | None,
    explicit: dict[str, Any] | None = None,
    devices: Any = None,
    owner: int | None = None,
) -> dict[str, Any]:
    """Resolve a persisted parent capture for inherit / member_default / explicit.

    ``explicit`` + ``target_kind=local`` stamps ``octop_device_target`` so
    ``_prepare_stream_request`` calls real ``resolve(..., target_kind=local)``
    (never a fake ``octop_execution_context`` without ``context_id``).
    """
    cfg = dict(snapshot.get("configurable") or {})
    mode = (policy or "member_default").strip() or "member_default"
    if mode not in {"inherit", "member_default", "explicit"}:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid dispatch target policy")
    if mode == "member_default":
        cfg.pop("octop_device_target", None)
        cfg.pop("octop_execution_context", None)
        cfg.pop("octop_explicit_working_dir", None)
        cfg["octop_target_policy"] = "member_default"
    elif mode == "explicit":
        target = explicit if isinstance(explicit, dict) else {}
        _validate_explicit_target(target)
        device_id = target.get("device_id")
        kind = target.get("target_kind") or ("device" if device_id else None)
        if kind == "local":
            # Intent only — resolve() creates the real ExecutionContext with context_id.
            cfg.pop("octop_execution_context", None)
            cfg.pop("octop_explicit_working_dir", None)
            stamped: dict[str, Any] = {
                "target_kind": "local",
                "device_id": None,
            }
            if target.get("working_dir") is not None:
                stamped["working_dir"] = target.get("working_dir")
            cfg["octop_device_target"] = stamped
            cfg["octop_target_policy"] = "explicit"
        elif device_id and devices is not None and owner is not None:
            device = devices.owned(owner, str(device_id))
            stamped = {
                "device_id": str(device_id),
                "grant_version": device.grant_version,
                "target_kind": "device",
            }
            if target.get("working_dir") is not None:
                stamped["working_dir"] = target.get("working_dir")
            cfg["octop_device_target"] = stamped
            cfg.pop("octop_explicit_working_dir", None)
            cfg.pop("octop_execution_context", None)
            cfg["octop_target_policy"] = "explicit"
        else:
            raise OctopError(
                ErrorCode.FORBIDDEN, "explicit device dispatch requires account device access"
            )
    else:
        cfg["octop_target_policy"] = "inherit"
    snapshot = {**snapshot, "configurable": cfg}
    return snapshot
