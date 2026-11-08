"""Record an admitted interactive request, never an internal model/tool step."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from octop.infra.db.services import RepoBundle
from octop.infra.utils.ulid import new_ulid


def record_user_request(
    repos: Any,
    owner: int,
    agent: str,
    thread: str,
    request: dict[str, Any],
    connection_id: str = "",
) -> None:
    if not isinstance(repos, RepoBundle):
        return
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    human = messages[-1]
    receipt = (
        repos.chat_input_repo.get(owner, connection_id[6:])
        if connection_id.startswith("queue:")
        else None
    )
    queued_id = None
    occurred_at = None
    if receipt and receipt["agent_id"] == agent and receipt["thread_id"] == thread:
        queued_id = f"steer:{connection_id[6:]}"
        occurred_at = float(receipt["created_at"])
    if isinstance(human, HumanMessage):
        if human.additional_kwargs.get("lc_source") in {"summarization", "pinned_skill"} or str(
            human.id or ""
        ).startswith("cron:"):
            return
        if queued_id:
            human.id = queued_id
        elif not human.id:
            human.id = new_ulid()
        identity = human.id
    elif isinstance(human, dict) and human.get("role", human.get("type")) in {"user", "human"}:
        if (human.get("additional_kwargs") or {}).get("lc_source") in {
            "summarization",
            "pinned_skill",
        } or str(human.get("id") or "").startswith("cron:"):
            return
        identity = str(queued_id or human.get("id") or new_ulid())
        human["id"] = identity
    else:
        return
    repos.thread_activity_repo.record(owner, agent, thread, f"human:{identity}", occurred_at)


def record_task_activity(
    repos: Any, owner: int, task_id: str, command_id: str, kind: str = "input"
) -> None:
    if not isinstance(repos, RepoBundle):
        return
    task = repos.work_item_repo.get(owner, task_id)
    if task is not None and task.get("origin_thread_id"):
        repos.thread_activity_repo.record(
            owner,
            str(task["agent_id"]),
            str(task["origin_thread_id"]),
            f"work:{task_id}:{kind}:{command_id.strip()}",
        )
