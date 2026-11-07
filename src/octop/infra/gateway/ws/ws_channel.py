"""Virtual IM channel that delivers Dashboard chat over WebSocket."""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from octop_gateway.channel import BaseChannel, MessageProcessor
from octop_gateway.constraints import ChannelConstraints
from octop_gateway.models import (
    AudioContent,
    ChannelSubject,
    ContentPart,
    FileContent,
    ImageContent,
    InboundMessage,
    TextContent,
    VideoContent,
)

from octop.i18n.domains.stream import format_stream_error
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.gateway.ws.ws_hub import WebSocketHub
from octop.infra.utils.locale import resolve_locale

logger = logging.getLogger(__name__)

WS_CHANNEL_ID = "octop-dashboard"


class WebSocketChannel(BaseChannel):
    """Routes chat turns through GlobalProcessor.iter_turn_chunks → WebSocket hub."""

    channel_type = ThreadRegistry.CHANNEL_DASHBOARD

    def __init__(
        self,
        processor: MessageProcessor,
        *,
        hub: WebSocketHub,
        channel_id: str = WS_CHANNEL_ID,
        on_chunk: Callable[[InboundMessage, dict[str, Any]], None] | None = None,
        emit_thread_changed: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(processor, channel_id=channel_id, debounce_seconds=0.0)
        self._hub = hub
        self._on_chunk = on_chunk
        self._emit_thread_changed = emit_thread_changed

    def _default_constraints(self) -> ChannelConstraints:
        return ChannelConstraints(
            show_thinking=True,
            show_tool_hints=True,
            send_rate_limit=None,
        )

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    def parse_inbound(self, raw_payload: Any) -> InboundMessage:
        if isinstance(raw_payload, InboundMessage):
            return raw_payload
        raise TypeError(f"websocket channel expects InboundMessage, got {type(raw_payload)!r}")

    def get_debounce_key(self, message: InboundMessage) -> str:
        """Lock and batch per thread so concurrent WS turns cannot interleave.

        Dashboard ``session_key`` is per user+agent; using it as the worker lock
        would serialize unrelated threads and let ``_drain_same_session`` merge
        turns from different conversations.
        """
        meta = message.metadata or {}
        thread_id = meta.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return f"thread:{thread_id.strip()}"
        session_key = meta.get("session_key")
        if isinstance(session_key, str) and session_key.strip():
            return session_key.strip()
        if message.channel_session_id:
            return message.channel_session_id
        subject_id = ""
        if message.channel_subject and message.channel_subject.subject_id:
            subject_id = message.channel_subject.subject_id
        return f"{message.tenant_id or ''}:{subject_id}"

    def should_batch_inbound(self, message: InboundMessage) -> bool:  # noqa: ARG002
        # Never concatenate two dashboard user_turns (would look like 串流).
        return False

    async def handle_inbound(self, raw_payload: Any) -> None:
        """Stream harness chunks to all thread subscribers (no delta batching)."""
        message = self.parse_inbound(raw_payload)

        if self._media_backend:
            await self._persist_media(message)

        msg_meta = message.metadata or {}
        conn_id = str(msg_meta.get("ws_connection_id") or "")
        if not conn_id:
            logger.warning("websocket inbound missing ws_connection_id")
            return

        thread_id = str(msg_meta.get("thread_id") or "").strip()
        if not thread_id:
            logger.warning("websocket inbound missing thread_id")
            await self._hub.push(conn_id, {"type": "error", "message": "missing thread_id"})
            await self._hub.push(conn_id, {"type": "done"})
            return

        self._track_subject(message)
        # Per-turn routing copy: do not write thread_id onto the shared
        # ChannelSubject (keyed by user), or concurrent threads 串流 via _send_*.
        subject_id = message.channel_subject.subject_id if message.channel_subject else ""
        tracked = self._known_subjects.get(subject_id) or ChannelSubject(
            subject_id=subject_id,
            first_seen=message.timestamp,
            last_seen=message.timestamp,
        )
        message.channel_subject = ChannelSubject(
            subject_id=tracked.subject_id,
            first_seen=tracked.first_seen,
            last_seen=tracked.last_seen,
            display_name=tracked.display_name,
            chat_type=tracked.chat_type,
            metadata={
                **(tracked.metadata or {}),
                "ws_connection_id": conn_id,
                "thread_id": thread_id,
            },
        )

        # Bind the originating connection so early chunks are delivered; extra
        # browsers / reconnects add subscribers via hub.subscribe without kicking
        # existing connections.
        self._hub.subscribe(thread_id, conn_id)

        processor = self._processor
        if not hasattr(processor, "iter_turn_chunks"):
            await self._hub.push_to_thread(
                thread_id,
                {"type": "error", "message": "processor does not support turn chunk streaming"},
            )
            await self._hub.push_to_thread(thread_id, {"type": "done"})
            return

        owner_user_id = _owner_user_id(message)
        agent_id = str(message.tenant_id or "").strip()
        # Queued HTTP inputs already emitted ``input`` on enqueue.
        if not conn_id.startswith("queue:"):
            await self._emit_lifecycle(
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                thread_id=thread_id,
                reason="input",
            )
        self._hub.mark_turn_active(thread_id)
        await self._emit_lifecycle(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            thread_id=thread_id,
            reason="running",
        )
        terminal_reason: str | None = "completed"
        last_run_id: str | None = None
        try:
            async for chunk in processor.iter_turn_chunks(message):
                if self._on_chunk is not None:
                    try:
                        self._on_chunk(message, chunk)
                    except Exception:
                        logger.exception("Could not persist chat input status thread=%s", thread_id)
                run_id = chunk.get("run_id") if isinstance(chunk, dict) else None
                if isinstance(run_id, str) and run_id.strip():
                    last_run_id = run_id.strip()
                ctype = chunk.get("type") if isinstance(chunk, dict) else None
                if ctype == "hitl_required":
                    terminal_reason = None
                    await self._emit_lifecycle(
                        owner_user_id=owner_user_id,
                        agent_id=agent_id,
                        thread_id=thread_id,
                        reason="attention",
                        run_id=last_run_id,
                    )
                elif ctype == "error":
                    terminal_reason = "failed"
                elif ctype == "run_phase":
                    phase = str(chunk.get("phase") or "")
                    if phase in {"completed", "failed", "cancelled"}:
                        terminal_reason = phase
                    elif phase == "paused":
                        terminal_reason = None
                        await self._emit_lifecycle(
                            owner_user_id=owner_user_id,
                            agent_id=agent_id,
                            thread_id=thread_id,
                            reason="attention",
                            run_id=last_run_id,
                        )
                    elif phase:
                        await self._emit_lifecycle(
                            owner_user_id=owner_user_id,
                            agent_id=agent_id,
                            thread_id=thread_id,
                            reason="running",
                            run_id=last_run_id,
                            phase=phase,
                        )
                # Never let delivery failures abort the harness turn — otherwise a
                # flaky client disconnect can stop generation mid-node and leave
                # an incomplete checkpoint.
                try:
                    await self._hub.push_to_thread(thread_id, chunk)
                except Exception:
                    logger.exception(
                        "websocket push failed thread=%s (turn continues)",
                        thread_id,
                    )
        except Exception as exc:
            logger.exception("websocket turn failed")
            terminal_reason = "failed"
            err_meta = message.metadata if isinstance(message.metadata, dict) else None
            locale = resolve_locale(
                channel_type=str(getattr(message, "channel_type", "") or ""),
                metadata=err_meta,
            )
            try:
                await self._hub.push_to_thread(
                    thread_id,
                    {"type": "error", "message": format_stream_error(exc, locale)},
                )
                await self._hub.push_to_thread(thread_id, {"type": "done"})
            except Exception:
                logger.exception("websocket failed to deliver error frame thread=%s", thread_id)
        finally:
            self._hub.mark_turn_idle(thread_id)
            if terminal_reason:
                await self._emit_lifecycle(
                    owner_user_id=owner_user_id,
                    agent_id=agent_id,
                    thread_id=thread_id,
                    reason=terminal_reason,
                    run_id=last_run_id,
                )

    async def _emit_lifecycle(
        self,
        *,
        owner_user_id: int | None,
        agent_id: str,
        thread_id: str,
        reason: str,
        run_id: str | None = None,
        phase: str | None = None,
    ) -> None:
        emit = self._emit_thread_changed
        if emit is None or owner_user_id is None or not agent_id:
            return
        try:
            await emit(
                owner_user_id=owner_user_id,
                agent_id=agent_id,
                thread_id=thread_id,
                reason=reason,
                run_id=run_id,
                phase=phase,
            )
        except Exception:
            logger.exception("thread.changed emit failed thread=%s reason=%s", thread_id, reason)

    async def _send_text(self, subject: ChannelSubject, text: str) -> None:
        if not text:
            return
        thread_id = str(subject.metadata.get("thread_id") or "").strip()
        if thread_id:
            await self._hub.push_to_thread(thread_id, {"type": "token", "content": text})
            await self._hub.push_to_thread(thread_id, {"type": "done"})
            return
        conn_id = str(subject.metadata.get("ws_connection_id") or "")
        if conn_id:
            await self._hub.push(conn_id, {"type": "token", "content": text})
            await self._hub.push(conn_id, {"type": "done"})

    async def _send_content(self, subject: ChannelSubject, parts: list[ContentPart]) -> None:
        text = "\n".join(p.text for p in parts if isinstance(p, TextContent) and p.text)
        if text:
            await self._send_text(subject, text)

    async def _send_media(self, subject: ChannelSubject, media: ContentPart) -> None:
        thread_id = str(subject.metadata.get("thread_id") or "").strip()
        conn_id = str(subject.metadata.get("ws_connection_id") or "")
        if not thread_id and not conn_id:
            return
        try:
            raw_bytes, mime = await self.load_media_bytes(media)
        except (ValueError, RuntimeError, OSError) as exc:
            logger.warning("websocket channel: failed to load media bytes: %s", exc)
            return

        frame: dict[str, Any] = {
            "type": "attachment",
            "kind": _media_kind(media),
            "mime_type": mime,
            "data": base64.b64encode(raw_bytes).decode("ascii"),
        }
        filename = getattr(media, "filename", None)
        if isinstance(filename, str) and filename.strip():
            frame["filename"] = filename.strip()
        alt = getattr(media, "alt_text", None)
        if isinstance(alt, str) and alt.strip():
            frame["alt_text"] = alt.strip()
        if thread_id:
            await self._hub.push_to_thread(thread_id, frame)
        else:
            await self._hub.push(conn_id, frame)


def _owner_user_id(message: InboundMessage) -> int | None:
    subject = message.channel_subject
    if subject is None:
        return None
    raw = subject.subject_id
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _media_kind(media: ContentPart) -> str:
    if isinstance(media, ImageContent):
        return "image"
    if isinstance(media, VideoContent):
        return "video"
    if isinstance(media, AudioContent):
        return "audio"
    if isinstance(media, FileContent):
        return "file"
    return "file"


__all__ = ["WS_CHANNEL_ID", "WebSocketChannel"]
