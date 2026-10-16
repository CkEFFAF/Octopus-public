"""0019: expert default target visibility + ask_agent target_policy (inherit|member_default|explicit)."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any, Literal

logger = logging.getLogger(__name__)

TargetPolicy = Literal["inherit", "member_default", "explicit"]
_PATCHED = False

# Per-invoke stamp so ask_agent does not mutate a shared configurable dict (concurrent bleed).
_PENDING_ASK_TARGET: ContextVar[dict[str, Any] | None] = ContextVar(
    "octop_pending_ask_target", default=None
)


def pending_ask_target() -> dict[str, Any] | None:
    """Return the in-flight ask_agent target_policy stamp, if any."""
    return _PENDING_ASK_TARGET.get()


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


def apply_target_policy(
    snapshot: dict[str, Any],
    *,
    policy: str | None,
    explicit: dict[str, Any] | None = None,
    devices: Any = None,
    owner: int | None = None,
) -> dict[str, Any]:
    """Mutate a PeerTaskTracker capture for inherit / member_default / explicit.

    ``explicit`` + ``target_kind=local`` stamps ``octop_device_target`` so
    ``_prepare_stream_request`` calls real ``resolve(..., target_kind=local)``
    (never a fake ``octop_execution_context`` without ``context_id``).
    """
    cfg = dict(snapshot.get("configurable") or {})
    mode = (policy or "inherit").strip() or "inherit"
    if mode == "member_default":
        cfg.pop("octop_device_target", None)
        cfg.pop("octop_execution_context", None)
        cfg.pop("octop_explicit_working_dir", None)
        cfg["octop_target_policy"] = "member_default"
    elif mode == "explicit":
        target = explicit if isinstance(explicit, dict) else {}
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
            # Fall back to inherit when explicit payload is incomplete.
            cfg["octop_target_policy"] = "inherit"
    else:
        cfg["octop_target_policy"] = "inherit"
    snapshot = {**snapshot, "configurable": cfg}
    return snapshot


def install_harness_target_patches() -> None:
    """Patch harness agent_list / ask_agent without bumping the wheel (OQ-2/OQ-3).

    Host teams use ``peer_invoke_mode="async"``; wrap async **and** sync (and both)
    so AC-04 target_policy is on the team Host main path.
    """
    global _PATCHED
    if _PATCHED:
        return
    try:
        from octop_harness.teams import tools as team_tools
    except ImportError:
        logger.warning("octop_harness.teams.tools unavailable; skip 0019 patches")
        return

    original_item = team_tools._agent_list_item

    def _agent_list_item(team: Any, entry: Any, language: Any) -> dict[str, Any]:
        item = original_item(team, entry, language)
        meta = entry.metadata or {}
        item["default_target"] = meta.get("default_target")
        item["model_ref"] = meta.get("model_ref")
        return item

    team_tools._agent_list_item = _agent_list_item

    original_build = team_tools.build_team_tools

    def build_team_tools(team: Any, *, peer_invoke_mode: Any = "both") -> list[Any]:
        from typing import Literal as TyLiteral

        from langchain_core.tools import StructuredTool
        from pydantic import AliasChoices, BaseModel, ConfigDict, Field

        tools = original_build(team, peer_invoke_mode=peer_invoke_mode)
        ask = next((t for t in tools if getattr(t, "name", None) == "ask_agent"), None)
        if ask is None:
            return tools
        original_coro = ask.coroutine
        if original_coro is None:
            return tools

        # Extend the mode-specific harness schema (async/sync/both) with target_policy.
        if peer_invoke_mode == "async":

            class AskAsyncWithTarget(BaseModel):
                model_config = ConfigDict(populate_by_name=True)
                expert: str = Field(
                    validation_alias=AliasChoices("expert", "agent"),
                    description="Target expert name or short id",
                )
                message: str = Field(description="Task or question for the target expert")
                user_question: str | None = Field(
                    default=None,
                    description="The user's original question, used when composing the follow-up",
                )
                target_policy: TyLiteral["inherit", "member_default", "explicit"] = Field(
                    default="inherit",
                    description=(
                        "inherit: use room/host execution target (default). "
                        "member_default: resolve the member's own device_binding. "
                        "explicit: require device_id or target_kind=local for this dispatch only."
                    ),
                )
                device_id: str | None = Field(
                    default=None,
                    description="When target_policy=explicit, the device to run on",
                )
                target_kind: TyLiteral["device", "local"] | None = Field(
                    default=None,
                    description="When target_policy=explicit, device or local",
                )
                working_dir: str | None = Field(
                    default=None,
                    description="Optional working directory for explicit override",
                )

        elif peer_invoke_mode == "sync":

            class AskSyncWithTarget(BaseModel):
                model_config = ConfigDict(populate_by_name=True)
                expert: str = Field(
                    validation_alias=AliasChoices("expert", "agent"),
                    description="Target expert name or short id",
                )
                message: str = Field(description="Task or question for the target expert")
                target_policy: TyLiteral["inherit", "member_default", "explicit"] = Field(
                    default="inherit",
                    description=(
                        "inherit: use room/host execution target (default). "
                        "member_default: resolve the member's own device_binding. "
                        "explicit: require device_id or target_kind=local for this dispatch only."
                    ),
                )
                device_id: str | None = Field(
                    default=None,
                    description="When target_policy=explicit, the device to run on",
                )
                target_kind: TyLiteral["device", "local"] | None = Field(
                    default=None,
                    description="When target_policy=explicit, device or local",
                )
                working_dir: str | None = Field(
                    default=None,
                    description="Optional working directory for explicit override",
                )

        else:

            class AskBothWithTarget(BaseModel):
                model_config = ConfigDict(populate_by_name=True)
                expert: str = Field(
                    validation_alias=AliasChoices("expert", "agent"),
                    description="Target expert name or short id",
                )
                message: str = Field(description="Task or question for the target expert")
                mode: TyLiteral["sync", "background"] = Field(
                    default="sync",
                    description=(
                        "sync: wait for an immediate answer (default). "
                        "background: delegate long work and get a proactive follow-up."
                    ),
                )
                user_question: str | None = Field(
                    default=None,
                    description="When mode=background, the user's original question",
                )
                target_policy: TyLiteral["inherit", "member_default", "explicit"] = Field(
                    default="inherit",
                    description=(
                        "inherit: use room/host execution target (default). "
                        "member_default: resolve the member's own device_binding. "
                        "explicit: require device_id or target_kind=local for this dispatch only."
                    ),
                )
                device_id: str | None = Field(
                    default=None,
                    description="When target_policy=explicit, the device to run on",
                )
                target_kind: TyLiteral["device", "local"] | None = Field(
                    default=None,
                    description="When target_policy=explicit, device or local",
                )
                working_dir: str | None = Field(
                    default=None,
                    description="Optional working directory for explicit override",
                )

        async def ask_agent(
            expert: str,
            message: str,
            mode: TyLiteral["sync", "background"] = "sync",
            user_question: str | None = None,
            target_policy: TyLiteral["inherit", "member_default", "explicit"] = "inherit",
            device_id: str | None = None,
            target_kind: TyLiteral["device", "local"] | None = None,
            working_dir: str | None = None,
        ) -> str:
            # Isolate per invoke via ContextVar — never mutate shared configurable in place.
            stamp: dict[str, Any] = {"octop_target_policy": target_policy}
            if target_policy == "explicit":
                stamp["octop_explicit_target"] = {
                    "device_id": device_id,
                    "target_kind": target_kind or ("device" if device_id else None),
                    "working_dir": working_dir,
                }
            else:
                stamp["octop_explicit_target"] = None
            token = _PENDING_ASK_TARGET.set(stamp)
            try:
                try:
                    result = await original_coro(
                        expert=expert,
                        message=message,
                        mode=mode,
                        user_question=user_question,
                    )
                except TypeError:
                    # sync/async harness schemas omit mode / user_question.
                    try:
                        result = await original_coro(
                            expert=expert,
                            message=message,
                            user_question=user_question,
                        )
                    except TypeError:
                        result = await original_coro(expert=expert, message=message)
                return str(result)
            finally:
                _PENDING_ASK_TARGET.reset(token)

        if peer_invoke_mode == "async":
            schema: type[BaseModel] = AskAsyncWithTarget
        elif peer_invoke_mode == "sync":
            schema = AskSyncWithTarget
        else:
            schema = AskBothWithTarget
        replacement = StructuredTool.from_function(
            coroutine=ask_agent,
            name="ask_agent",
            description=ask.description,
            args_schema=schema,
        )
        return [replacement if getattr(t, "name", None) == "ask_agent" else t for t in tools]

    team_tools.build_team_tools = build_team_tools
    _PATCHED = True


__all__ = [
    "TargetPolicy",
    "apply_target_policy",
    "binding_from_row",
    "enrich_peer_metadata",
    "expert_default_target",
    "install_harness_target_patches",
    "model_ref_for_row",
    "pending_ask_target",
]
