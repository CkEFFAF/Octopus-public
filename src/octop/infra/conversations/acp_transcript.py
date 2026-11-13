"""Durable transcripts from actual ACP sessions, never from formatted tool claims."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, message_to_dict

from octop.i18n import tr
from octop.infra.conversations.collaboration import SENDER_KEY
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import live_message_inputs
from octop.infra.history.service import HistoryArchive
from octop.infra.utils.log_redaction import redact_secrets
from octop.infra.utils.ulid import new_ulid


class ACPTranscript:
    def __init__(
        self, repos: RepoBundle, archive: HistoryArchive | None, notify: Any = None
    ) -> None:
        self.repos, self.archive, self.notify = repos, archive, notify
        self.registry = ThreadRegistry(
            session_repo=repos.session_repo, thread_repo=repos.thread_repo
        )

    async def begin(
        self,
        *,
        owner: int,
        agent_id: str,
        parent: str,
        runner: str,
        acp_session_id: str,
        device_id: str | None,
        prompt: str,
        private_values: list[str],
    ) -> dict[str, Any]:
        row, expert = await asyncio.gather(
            asyncio.to_thread(self.repos.thread_repo.get, parent),
            asyncio.to_thread(self.repos.agent_repo.get, agent_id),
        )
        if row is None or (row.user_id, row.agent_id) != (owner, agent_id) or expert is None:
            raise ValueError("ACP parent conversation unavailable")
        actor = {"kind": "expert", "id": agent_id, "name": expert.name}
        source = {
            "kind": "acp" if acp_session_id else "acp_attempt",
            "parent_thread_id": parent,
            "runner_name": runner,
            "acp_session_id": acp_session_id,
        }
        if device_id:
            source["device_id"] = device_id
        digest = hashlib.sha256(
            repr(
                (owner, agent_id, parent, device_id, runner, acp_session_id or new_ulid())
            ).encode()
        ).hexdigest()
        thread = await self.registry.get_or_create_by_key(
            session_key=f"{agent_id}:dashboard:{owner}:acp-outbound-{digest}",
            agent_id=agent_id,
            user_id=owner,
            channel_type="dashboard",
            channel_metadata={
                "source": "acp" if acp_session_id else "acp_attempt",
                "category": "agent_collaboration",
                "actor": actor,
                "collaboration_source": source,
            },
        )
        await asyncio.to_thread(
            self.repos.thread_repo.set_title_if_null, thread, f"{expert.name} · {runner}"
        )
        turn = (
            await asyncio.to_thread(self.archive.begin, agent_id, thread) if self.archive else None
        )
        identity = new_ulid()
        record: dict[str, Any] = {
            "thread_id": thread,
            "owner": owner,
            "agent_id": agent_id,
            "parent": parent,
            "runner": runner,
            "turn": turn,
            "id": identity,
            "private_values": private_values,
            "prompt": self.clean(prompt, private_values),
            "actor": actor,
            "response": "",
        }
        await self.update(record, "", "running")
        await self._notify(record, "created")
        return record

    @staticmethod
    def clean(text: str, private_values: list[str]) -> str:
        text = redact_secrets(text)
        text = re.sub(r"\b(?:oaa_|oak_)[A-Za-z0-9_-]+", "[REDACTED]", text)
        for value in private_values:
            if len(value) >= 4:
                text = text.replace(value, "[REDACTED]")
        return text[:128000]

    def _messages(self, record: dict[str, Any], state: str) -> list[Any]:
        responder = {"kind": "acp", "id": record["runner"], "name": record["runner"]}
        text = record["response"]
        if not text and state != "running":
            text = tr("agentCollaboration.acp_state", "en", state=state)
        messages: list[Any] = [
            HumanMessage(
                content=record["prompt"],
                id=f"acp:{record['id']}:request",
                additional_kwargs={SENDER_KEY: record["actor"]},
            ),
        ]
        if not text and state == "running":
            return messages
        messages.append(
            AIMessage(
                content=text,
                id=f"acp:{record['id']}:response",
                additional_kwargs={SENDER_KEY: responder, "octop_collaboration_state": state},
            )
        )
        return messages

    async def update(self, record: dict[str, Any], text: str, state: str) -> None:
        record["response"] = self.clean(text, record["private_values"])
        turn = record["turn"]
        if self.archive and turn and turn["format"] == "v2":
            wires = [message_to_dict(msg) for msg in self._messages(record, state)]
            await asyncio.to_thread(self.archive.save_messages, turn, wires)

    async def finish(self, record: dict[str, Any], text: str, state: str) -> None:
        await self.update(record, text, state)
        turn = record["turn"]
        if self.archive and turn:
            await asyncio.to_thread(self.archive.finish, turn["id"], state)
        if not turn or turn["format"] != "v2":
            messages = live_message_inputs(self._messages(record, state))
            await asyncio.to_thread(
                self.repos.thread_message_repo.append_legacy_interval, record["thread_id"], messages
            )
            await asyncio.to_thread(
                self.repos.thread_message_repo.mark_projection, record["thread_id"], "ready"
            )
        await asyncio.to_thread(self.repos.thread_repo.touch_last_active, record["thread_id"])
        await self._notify(record, "completed" if state == "completed" else "updated")

    async def _notify(self, record: dict[str, Any], reason: str) -> None:
        if self.notify:
            await self.notify(
                owner_user_id=record["owner"],
                agent_id=record["agent_id"],
                thread_id=record["thread_id"],
                reason=reason,
            )
