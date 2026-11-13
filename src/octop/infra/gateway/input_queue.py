"""Durable dashboard input scheduling under the existing per-thread session lock."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from octop_gateway.models import InboundMessage

from octop.infra.agents.teams import is_team_agent
from octop.infra.bridge.ids import is_bridge_agent_id
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.gateway.gateway import Gateway

logger = logging.getLogger(__name__)


class ChatInputQueue:
    def __init__(self, repos: RepoBundle, agents: AgentManager, gateway: Gateway) -> None:
        self.repos, self.agents, self.gateway = repos, agents, gateway
        self._worker: asyncio.Task[None] | None = None
        self._dispatches: dict[str, asyncio.Task[None]] = {}
        self._scan_after = 0

    def assert_scope(self, owner: int, agent_id: str, thread_id: str) -> None:
        row = self.repos.thread_repo.get(thread_id)
        agent = self.repos.agent_repo.get(agent_id)
        user = self.repos.user_repo.get(owner)
        if (
            is_bridge_agent_id(agent_id)
            or row is None
            or row.channel_type != "dashboard"
            or row.agent_id != agent_id
            or row.user_id != owner
            or agent is None
            or user is None
            or user.disabled
            or (agent.user_id != owner and not agent.is_shared and user.role != "admin")
        ):
            raise OctopError(
                ErrorCode.FORBIDDEN, "chat input scope is not an owned local Dashboard thread"
            )

    def list(self, owner: int, agent_id: str, thread_id: str) -> dict[str, Any]:
        self.assert_scope(owner, agent_id, thread_id)
        supported = self._supports_persistent_inputs(agent_id)
        self.repos.chat_input_repo.reconcile_applied(owner, agent_id, thread_id)
        return {
            "inputs": self.repos.chat_input_repo.list(owner, agent_id, thread_id),
            "runtime": self.agents.steering_status(agent_id, thread_id),
            "capabilities": {"queue": supported, "steer": supported},
        }

    def _supports_persistent_inputs(self, agent_id: str) -> bool:
        return not is_bridge_agent_id(agent_id) and not is_team_agent(self.agents.get_row(agent_id))

    def enqueue(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        command_id: str,
        snapshot: dict[str, Any],
        inbound: InboundMessage,
        *,
        request_key: str,
    ) -> dict[str, Any]:
        self.assert_scope(owner, agent_id, thread_id)
        if not self._supports_persistent_inputs(agent_id):
            raise ValueError("input_queue_unsupported")
        existing = self.existing_queue(owner, agent_id, thread_id, command_id, request_key)
        if existing is not None:
            self.repos.thread_activity_repo.record(
                owner,
                agent_id,
                thread_id,
                f"human:steer:{command_id}",
                float(existing["created_at"]),
            )
            return existing
        receipt = self.repos.chat_input_repo.create(
            owner,
            agent_id,
            thread_id,
            command_id,
            kind="chat_input",
            run_id=command_id,
            status="queued",
            payload={
                "command_id": command_id,
                "request_key": request_key,
                "snapshot": {**snapshot, "id": command_id, "text": inbound.text},
                "inbound": inbound.model_dump(mode="json"),
            },
        )
        self.repos.thread_activity_repo.record(
            owner, agent_id, thread_id, f"human:steer:{command_id}", float(receipt["created_at"])
        )
        return receipt

    def existing_queue(
        self, owner: int, agent_id: str, thread_id: str, command_id: str, request_key: str
    ) -> dict[str, Any] | None:
        self.assert_scope(owner, agent_id, thread_id)
        item = self.repos.chat_input_repo.get(owner, command_id)
        if item is not None and (
            item["agent_id"] != agent_id
            or item["thread_id"] != thread_id
            or (
                item["kind"] != "chat_input"
                and not (
                    item["kind"] == "chat_steer" and item["payload"].get("_promoted_from_queue")
                )
            )
            or item["payload"].get("request_key") != request_key
        ):
            raise ValueError("command_conflict")
        return item

    def withdraw(
        self, owner: int, agent_id: str, thread_id: str, command_id: str
    ) -> dict[str, Any]:
        self.assert_scope(owner, agent_id, thread_id)
        item = self.repos.chat_input_repo.get(owner, command_id)
        if item is None or item["agent_id"] != agent_id or item["thread_id"] != thread_id:
            raise OctopError(ErrorCode.NOT_FOUND, "chat input not found")
        if item["status"] == "withdrawn":
            return item
        if not self.repos.chat_input_repo.transition(owner, command_id, "queued", "withdrawn"):
            raise ValueError("input_already_dispatched")
        return self.repos.chat_input_repo.get(owner, command_id) or item

    def steer(
        self, owner: int, agent_id: str, thread_id: str, command_id: str, run_id: str, text: str
    ) -> dict[str, Any]:
        self.assert_scope(owner, agent_id, thread_id)
        if not self._supports_persistent_inputs(agent_id):
            raise ValueError("steering_unsupported")
        item = self.repos.chat_input_repo.create(
            owner,
            agent_id,
            thread_id,
            command_id,
            kind="chat_steer",
            run_id=run_id,
            status="requested",
            payload={"command_id": command_id, "text": text},
        )
        if item["status"] != "requested":
            return item
        outcome = self.agents.steer_stream(agent_id, thread_id, command_id, text, run_id=run_id)
        self.repos.chat_input_repo.transition(owner, command_id, "requested", outcome["status"])
        return {
            **(self.repos.chat_input_repo.get(owner, command_id) or item),
            "phase": outcome["phase"],
        }

    def dismiss(self, owner: int, agent_id: str, thread_id: str, command_id: str) -> dict[str, Any]:
        """Hide a terminal/unconfirmed receipt without cancelling or replaying work."""
        self.assert_scope(owner, agent_id, thread_id)
        item = self.repos.chat_input_repo.get(owner, command_id)
        if item is None or item["agent_id"] != agent_id or item["thread_id"] != thread_id:
            raise OctopError(ErrorCode.NOT_FOUND, "chat input not found")
        if item["status"] == "dismissed":
            return item
        if item["status"] not in {
            "unknown",
            "failed",
            "rejected",
        } or not self.repos.chat_input_repo.transition(
            owner, command_id, item["status"], "dismissed"
        ):
            raise ValueError("input_not_dismissible")
        return self.repos.chat_input_repo.get(owner, command_id) or item

    async def prepare_steering_input(
        self, owner: int, agent_id: str, thread_id: str, inbound: InboundMessage
    ) -> HumanMessage | None:
        """Validate media before creating or claiming any delivery receipt."""
        self.assert_scope(owner, agent_id, thread_id)
        if inbound.text.lstrip().startswith("/"):
            raise ValueError("steering_requires_plain_text")
        attachments = (inbound.metadata or {}).get("octop_inbound_attachments")
        if not attachments:
            return None
        if any(isinstance(a, dict) and a.get("kind") == "image" for a in attachments):
            runtime = self.agents.steering_status(agent_id, thread_id) or {}
            model = runtime.get("model") or self.agents.get_thread_model(agent_id, thread_id)
            if model and not self.agents.providers_for_agent(agent_id).is_model_ref_multimodal(
                model
            ):
                raise ValueError("steering_image_model_unsupported")
        return await self.gateway.processor.prepare_steering_message(
            inbound, agent_id, owner, thread_id
        )

    async def prepare_and_promote(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        command_id: str,
        run_id: str,
        *,
        cancel_tools: bool = False,
    ) -> dict[str, Any]:
        """Revalidate canonical attachments before atomically admitting a queued message."""
        self.assert_scope(owner, agent_id, thread_id)
        item = self.repos.chat_input_repo.get(owner, command_id)
        if item is None or item["agent_id"] != agent_id or item["thread_id"] != thread_id:
            raise OctopError(ErrorCode.NOT_FOUND, "chat input not found")
        if item["kind"] == "chat_steer":
            return self.promote_to_steer(
                owner, agent_id, thread_id, command_id, run_id, cancel_tools=cancel_tools
            )
        inbound = InboundMessage.model_validate(item["payload"].get("inbound"))
        prepared = await self.prepare_steering_input(owner, agent_id, thread_id, inbound)
        return self.promote_to_steer(
            owner,
            agent_id,
            thread_id,
            command_id,
            run_id,
            cancel_tools=cancel_tools,
            message=prepared,
        )

    def promote_to_steer(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        command_id: str,
        run_id: str,
        *,
        cancel_tools: bool = False,
        message: HumanMessage | None = None,
    ) -> dict[str, Any]:
        self.assert_scope(owner, agent_id, thread_id)
        if not self._supports_persistent_inputs(agent_id):
            raise ValueError("steering_unsupported")
        item = self.repos.chat_input_repo.get(owner, command_id)
        if item is None or item["agent_id"] != agent_id or item["thread_id"] != thread_id:
            raise OctopError(ErrorCode.NOT_FOUND, "chat input not found")
        payload = item["payload"]
        if item["kind"] == "chat_steer" and payload.get("_promoted_from_queue"):
            if item["run_id"] != run_id or bool(payload.get("cancel_tools")) != cancel_tools:
                raise ValueError("command_conflict")
            return item
        if item["kind"] != "chat_input" or item["status"] != "queued":
            raise ValueError("input_not_queued")

        snapshot = payload.get("snapshot")
        inbound = payload.get("inbound")
        text = snapshot.get("text") if isinstance(snapshot, dict) else None
        content = inbound.get("content") if isinstance(inbound, dict) else None
        plain_text = (
            isinstance(text, str)
            and bool(text.strip())
            and len(text.strip()) <= 20_000
            and not text.lstrip().startswith("/")
            and not snapshot.get("attachments")
            and isinstance(content, list)
            and bool(content)
            and all(isinstance(part, dict) and part.get("type") == "text" for part in content)
            and "".join(str(part.get("text") or "") for part in content).strip() == text.strip()
        )
        verified_media = (
            message is not None
            and isinstance(text, str)
            and len(text) <= 20_000
            and not text.lstrip().startswith("/")
            and bool(message.additional_kwargs.get("octop_inbound_attachments"))
            and isinstance(inbound, dict)
            and InboundMessage.model_validate(inbound).text.strip() == text.strip()
        )
        if not plain_text and not verified_media:
            raise ValueError("steering_requires_plain_text")
        assert isinstance(text, str)

        promoted, claimed = self.repos.chat_input_repo.promote_queued_to_steer(
            owner, agent_id, thread_id, command_id, run_id, text.strip(), cancel_tools=cancel_tools
        )
        if promoted is None:
            raise OctopError(ErrorCode.NOT_FOUND, "chat input not found")
        if not claimed:
            return promoted
        try:
            options: dict[str, Any] = {}
            if cancel_tools:
                options["cancel_tools"] = True
            if message is not None:
                options["message"] = message
            outcome = self.agents.steer_stream(
                agent_id,
                thread_id,
                command_id,
                text.strip(),
                run_id=run_id,
                **options,
            )
        except Exception:
            logger.exception("Promoted chat input outcome is unknown command=%s", command_id)
            self.repos.chat_input_repo.transition(owner, command_id, "requested", "unknown")
            return self.repos.chat_input_repo.get(owner, command_id) or promoted

        status = outcome.get("status")
        if status == "accepted":
            self.repos.chat_input_repo.transition(owner, command_id, "requested", "accepted")
        elif status in {"inactive", "stale_run", "busy", "conflict", "rejected"}:
            restored = self.repos.chat_input_repo.restore_promoted_queue(owner, command_id, run_id)
            if restored is not None:
                raise ValueError(f"steering_{status}")
            return self.repos.chat_input_repo.get(owner, command_id) or promoted
        else:
            self.repos.chat_input_repo.transition(owner, command_id, "requested", "unknown")
        return {
            **(self.repos.chat_input_repo.get(owner, command_id) or promoted),
            "phase": outcome.get("phase"),
        }

    def observe(self, message: InboundMessage, chunk: dict[str, Any]) -> None:
        subject = message.channel_subject
        if subject is None:
            return
        owner = int(subject.subject_id)
        if chunk.get("type") == "error":
            message.metadata["chat_input_outcome"] = "failed"
        elif chunk.get("type") == "hitl_required":
            message.metadata["chat_input_outcome"] = "paused"
        elif (
            chunk.get("type") == "run_phase"
            and chunk.get("phase") in {"completed", "failed", "cancelled", "paused"}
            and message.metadata.get("chat_input_outcome") not in {"failed", "paused"}
        ):
            message.metadata["chat_input_outcome"] = chunk["phase"]
        if chunk.get("type") == "steering_applied":
            command_id = str(chunk.get("command_id") or "")
            self.repos.chat_input_repo.transition(owner, command_id, "accepted", "applied")
        elif chunk.get("type") == "run_phase" and chunk.get("phase") in {
            "completed",
            "failed",
            "cancelled",
            "paused",
        }:
            thread_id = str((message.metadata or {}).get("thread_id") or "")
            self.repos.chat_input_repo.finish_run(
                owner, str(message.tenant_id), thread_id, str(chunk.get("run_id") or "")
            )

    def start(self) -> None:
        self.repos.chat_input_repo.recover()
        self._worker = asyncio.create_task(self._run(), name="dashboard-input-queue")

    async def close(self) -> None:
        tasks = [*self._dispatches.values()]
        if self._worker is not None:
            tasks.append(self._worker)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._dispatches.clear()

    async def _run(self) -> None:
        while True:
            try:
                items = self.repos.chat_input_repo.ready(after_seq=self._scan_after)
                self._scan_after = items[-1]["seq"] if items else 0
                for item in items:
                    thread_id = item["thread_id"]
                    if thread_id in self._dispatches:
                        continue
                    task = asyncio.create_task(
                        self._dispatch(item), name=f"queued-input:{thread_id}"
                    )
                    self._dispatches[thread_id] = task
                    task.add_done_callback(partial(self._dispatch_done, thread_id))
            except Exception:
                logger.exception("Could not scan durable chat inputs")
            await asyncio.sleep(0.5)

    def _dispatch_done(self, thread_id: str, task: asyncio.Task[None]) -> None:
        self._dispatches.pop(thread_id, None)

    async def _dispatch(self, item: dict[str, Any]) -> None:
        owner, agent_id, thread_id = int(item["owner_user_id"]), item["agent_id"], item["thread_id"]
        command_id = item["payload"]["command_id"]
        try:
            self.assert_scope(owner, agent_id, thread_id)
            self.agents.get_agent(agent_id)
            manager = self.gateway.channel_manager
            if manager is None:
                return

            async def operation() -> None:
                self.assert_scope(owner, agent_id, thread_id)
                inbound = InboundMessage.model_validate(item["payload"]["inbound"])
                meta = dict(inbound.metadata or {})
                if self.gateway.processor.hitl_coordinator.store.resolve_pending_for_thread(
                    thread_id, agent_id=agent_id, user_id=owner
                ):
                    return
                agent = self.agents.get_agent(agent_id)
                if agent.checkpointer:
                    state = await agent.graph.aget_state({"configurable": {"thread_id": thread_id}})
                    if any(task.interrupts for task in state.tasks):
                        return
                if not self.repos.chat_input_repo.transition(
                    owner, command_id, "queued", "dispatching"
                ):
                    return
                user = self.repos.user_repo.get(owner)
                meta["user_is_admin"] = bool(user and user.role == "admin")
                meta["ws_connection_id"] = f"queue:{command_id}"
                modification_id = item["payload"].get("snapshot", {}).get("modification_request_id")
                if modification_id:
                    modification = self.repos.workbench_repo.get(owner, modification_id)
                    if modification is None or (
                        modification.get("agent_id"),
                        modification.get("thread_id"),
                        modification.get("command_id"),
                    ) != (agent_id, thread_id, command_id):
                        raise ValueError("MODIFICATION_QUEUE_BINDING_INVALID")
                    meta["octop_modification_request_id"] = modification_id
                inbound.metadata = meta
                status = "applied"
                try:
                    await self.gateway.ws_hub.push_to_thread(
                        thread_id,
                        {
                            "type": "user",
                            "command_id": command_id,
                            "content": item["payload"]["snapshot"].get("text", ""),
                            "source": "dashboard_queue",
                            "snapshot": item["payload"]["snapshot"],
                        },
                    )
                    await self.gateway.dispatch_dashboard_input(inbound)
                    status = str(inbound.metadata.get("chat_input_outcome") or "applied")
                except asyncio.CancelledError:
                    status = "unknown"
                    raise
                except Exception:
                    status = "failed"
                    logger.exception("Queued chat input failed command=%s", command_id)
                finally:
                    self.repos.chat_input_repo.transition(owner, command_id, "dispatching", status)

            await manager.run_in_session(
                self.gateway.dashboard_channel_id, f"thread:{thread_id}", operation
            )
        except OctopError as exc:
            if exc.code in {ErrorCode.AGENT_NOT_RUNNING, ErrorCode.AGENT_FAILED}:
                return
            self.repos.chat_input_repo.transition(owner, command_id, "queued", "rejected")
        except Exception:
            logger.exception("Cannot dispatch queued input command=%s", command_id)
            self.repos.chat_input_repo.transition(owner, command_id, "queued", "failed")
