"""0042 helpers: resolve immutable origin_thread delivery targets."""

from __future__ import annotations

import logging
from typing import Any

from octop.infra.cron.self_reminder import (
    ERR_ORIGIN_THREAD_UNAVAILABLE,
    backfill_origin_from_session,
    is_self_reminder_row,
    preserve_origin_keys,
)
from octop.infra.db.repos.sessions import SessionRow
from octop.infra.gateway.threads import ThreadRegistry

logger = logging.getLogger(__name__)


class OriginThreadError(ValueError):
    """Raised when a self-reminder cannot safely target its origin thread."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def care_session_key(*, agent_id: str, owner_user_id: int) -> str:
    """Stable dedicated care session (DEC-0042-05 option ②)."""
    return ThreadRegistry.make_key(
        agent_id=agent_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        channel_subject_id=str(owner_user_id),
        channel_chat_type="care",
    )


def read_configured_care_thread_id(agent_row: Any) -> str | None:
    """Optional fixed care thread from agent config_json.care_thread_id."""
    import json

    raw = getattr(agent_row, "config_json", None) if agent_row is not None else None
    if not raw:
        return None
    try:
        cfg = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(cfg, dict):
        return None
    tid = cfg.get("care_thread_id")
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    return None


def ensure_pin_session(
    *,
    session_repo: Any,
    thread_id: str,
    agent_id: str,
    user_id: int,
    channel_type: str = ThreadRegistry.CHANNEL_DASHBOARD,
) -> SessionRow:
    """Return a session bound to *thread_id*, creating a pin key if rebound away."""
    bound: list[SessionRow] = [
        s
        for s in session_repo.list_by_thread(thread_id)
        if s.agent_id == agent_id and int(s.user_id) == int(user_id)
    ]
    if bound:
        dash = next(
            (s for s in bound if s.channel_type == ThreadRegistry.CHANNEL_DASHBOARD),
            None,
        )
        return dash or bound[0]

    pin_key = ThreadRegistry.make_key(
        agent_id=agent_id,
        channel_type=channel_type,
        channel_subject_id=str(user_id),
        channel_chat_type=f"origin:{thread_id}",
    )
    session_repo.upsert(
        session_key=pin_key,
        agent_id=agent_id,
        user_id=user_id,
        channel_type=channel_type,
        chat_type=ThreadRegistry.CHAT_TYPE_DM,
        thread_id=thread_id,
        channel_subject_id=str(user_id),
        channel_chat_type=f"origin:{thread_id}",
        channel_metadata={
            "channel_type": channel_type,
            "user_id": user_id,
            "origin_pin": True,
        },
    )
    row: SessionRow | None = session_repo.get(pin_key)
    if row is None:
        raise OriginThreadError(ERR_ORIGIN_THREAD_UNAVAILABLE, "failed to pin origin session")
    return row


def prepare_self_reminder_command(
    command: Any,
    row: Any,
    *,
    session_repo: Any,
    thread_repo: Any,
    cron_repo: Any | None = None,
) -> Any:
    """Attach validated origin_thread_id to a delivery command; persist backfill.

    Raises OriginThreadError on missing/unavailable targets (DEC-0042-03/04).
    """
    from dataclasses import replace

    if not is_self_reminder_row(row):
        return command

    origin, meta, err = backfill_origin_from_session(
        row, session_repo=session_repo, thread_repo=thread_repo
    )
    # Persist backfill / needs_retarget without clobbering other keys.
    if cron_repo is not None:
        current = dict(getattr(row, "meta", None) or {})
        merged = preserve_origin_keys(current, meta)
        if merged != current:
            cron_repo.set_meta(str(row.cron_id), merged)

    if err:
        raise OriginThreadError(err)

    assert origin is not None
    source_kind = "self_reminder"
    return replace(
        command,
        origin_thread_id=origin,
        source_kind=source_kind,
    )


def resolve_delivery_session(
    *,
    command: Any,
    session_repo: Any,
    thread_repo: Any,
    gateway: Any,
) -> SessionRow:
    """Resolve the session used for lock/history/push for one delivery."""
    origin = getattr(command, "origin_thread_id", None)
    if origin:
        thread = thread_repo.get(origin)
        if thread is None:
            raise OriginThreadError(ERR_ORIGIN_THREAD_UNAVAILABLE)
        if str(thread.agent_id) != command.agent_id or int(thread.user_id) != int(command.user_id):
            raise OriginThreadError(ERR_ORIGIN_THREAD_UNAVAILABLE)
        return ensure_pin_session(
            session_repo=session_repo,
            thread_id=origin,
            agent_id=command.agent_id,
            user_id=command.user_id,
            channel_type=str(thread.channel_type or ThreadRegistry.CHANNEL_DASHBOARD),
        )

    # Non-origin path: live session_key binding (reports / ordinary cron / IM).
    session: SessionRow = gateway.require_session(command.agent_id, command.session_key)
    if (session.user_id, session.agent_id) != (command.user_id, command.agent_id):
        raise ValueError("cron session does not belong to user or agent (mismatch)")
    return session


__all__ = [
    "OriginThreadError",
    "care_session_key",
    "ensure_pin_session",
    "prepare_self_reminder_command",
    "read_configured_care_thread_id",
    "resolve_delivery_session",
]
