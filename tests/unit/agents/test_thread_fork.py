"""Tests for conversation fork-from-assistant-message."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from octop.infra.agents.threads.fork import (
    _fork_title,
    find_assistant_fork_index,
    fork_dashboard_thread,
    write_checkpoint_messages,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry


def test_fork_title_suffix() -> None:
    assert _fork_title("My chat", "en") == "My chat (fork)"
    assert _fork_title("My chat", "zh") == "My chat（分叉）"
    assert _fork_title(None, "en") == "Forked chat"
    assert _fork_title("", "zh") == "分叉对话"


def test_find_assistant_fork_index_by_suffix_count() -> None:
    messages = [
        HumanMessage(content="one", id="h1"),
        AIMessage(content="a1", id="a1"),
        HumanMessage(content="two", id="h2"),
        AIMessage(content="a2", id="a2"),
        HumanMessage(content="three", id="h3"),
        AIMessage(content="a3", id="a3"),
    ]
    assert find_assistant_fork_index(messages, message_id="x", assistant_turns_from_end=2) == 3
    assert find_assistant_fork_index(messages, message_id="x", assistant_turns_from_end=1) == 5
    assert find_assistant_fork_index(messages, message_id="x", assistant_turns_from_end=3) == 1


def test_find_assistant_fork_index_skips_tool_call_shells_even_with_text() -> None:
    messages = [
        HumanMessage(content="q", id="h1"),
        AIMessage(
            content="let me search",
            id="a-tool",
            tool_calls=[{"id": "c1", "name": "search", "args": {}}],
        ),
        ToolMessage(content="hit", id="t1", tool_call_id="c1"),
        AIMessage(content="final answer", id="a-final"),
    ]
    # Intermediate tool-call AI must not count as an answer turn.
    assert find_assistant_fork_index(messages, message_id="x", assistant_turns_from_end=1) == 3
    assert find_assistant_fork_index(messages, assistant_turns_from_end=1) == 3


def test_find_assistant_fork_index_trusts_turns_when_content_mismatches() -> None:
    messages = [
        HumanMessage(content="keep", id="h1"),
        AIMessage(content="first", id="a1"),
        HumanMessage(content="next", id="h2"),
        AIMessage(content="fork-me", id="a2"),
    ]
    # Client UUID + drifted content must not override the preferred locator.
    idx = find_assistant_fork_index(
        messages,
        message_id="client-uuid",
        content="other text",
        assistant_turns_from_end=1,
    )
    assert idx == 3


def test_find_assistant_fork_index_by_content_fallback() -> None:
    messages = [
        HumanMessage(content="alpha", id="h1"),
        AIMessage(content="reply-a", id="a1"),
        HumanMessage(content="beta", id="h2"),
        AIMessage(content="reply-b", id="a2"),
    ]
    assert find_assistant_fork_index(messages, message_id="missing", content="reply-b") == 3


@pytest.mark.parametrize("suffix", [1, 2])
def test_find_assistant_fork_index_preserves_exact_id_when_ui_count_drifts(suffix: int) -> None:
    messages = [
        HumanMessage(content="first question", id="h1"),
        AIMessage(content="same answer", id="a1"),
        HumanMessage(content="second question", id="h2"),
        AIMessage(content="same answer", id="a2"),
        AIMessage(content="", id="hidden-empty"),
    ]
    # Empty checkpoint messages are hidden in the UI. New source replies can
    # also arrive after the client counted the visible answers.
    assert (
        find_assistant_fork_index(
            messages,
            message_id="a1",
            content="same answer",
            assistant_turns_from_end=suffix,
        )
        == 1
    )


def test_find_assistant_fork_index_matches_live_text_when_ui_count_drifts() -> None:
    messages = [
        HumanMessage(content="question", id="h1"),
        AIMessage(content="selected answer", id="a1"),
        AIMessage(content="", id="hidden-empty"),
        HumanMessage(content="later question", id="h2"),
        AIMessage(content="later answer", id="a2"),
    ]
    assert (
        find_assistant_fork_index(
            messages,
            message_id="client-uuid",
            content="selected answer",
            assistant_turns_from_end=2,
        )
        == 1
    )


def test_find_assistant_fork_index_uses_count_to_disambiguate_repeated_live_text() -> None:
    messages = [
        HumanMessage(content="first question", id="h1"),
        AIMessage(content="same answer", id="a1"),
        HumanMessage(content="second question", id="h2"),
        AIMessage(content="same answer", id="a2"),
    ]
    assert (
        find_assistant_fork_index(
            messages,
            message_id="client-uuid",
            content="same answer",
            assistant_turns_from_end=2,
        )
        == 1
    )


def test_find_assistant_fork_index_missing_raises() -> None:
    messages = [HumanMessage(content="only user", id="h1")]
    with pytest.raises(OctopError) as exc:
        find_assistant_fork_index(messages, message_id="a1")
    assert exc.value.code is ErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_write_checkpoint_messages_skips_empty() -> None:
    graph = SimpleNamespace(aupdate_state=AsyncMock())
    harness = SimpleNamespace(graph=graph)
    await write_checkpoint_messages(harness, thread_id="thr_new", messages=[])
    graph.aupdate_state.assert_not_called()


@pytest.mark.asyncio
async def test_fork_dashboard_thread_copies_through_assistant_and_rebinds() -> None:
    source_id = "thr_src"
    messages = [
        HumanMessage(content="first", id="h1"),
        AIMessage(content="ok", id="a1"),
        ToolMessage(content="tool", id="t1", tool_call_id="c1"),
        HumanMessage(content="second", id="h2"),
        AIMessage(content="later", id="a2"),
    ]
    store: dict[str, list[Any]] = {source_id: list(messages)}
    graph = SimpleNamespace()

    async def aget_state(config: dict[str, Any]) -> SimpleNamespace:
        tid = config["configurable"]["thread_id"]
        return SimpleNamespace(values={"messages": list(store.get(tid, []))})

    async def aupdate_state(config: dict[str, Any], values: dict[str, Any], **_k: Any) -> None:
        tid = config["configurable"]["thread_id"]
        store.setdefault(tid, []).extend(list(values.get("messages") or []))

    graph.aget_state = aget_state
    graph.aupdate_state = aupdate_state
    harness = SimpleNamespace(graph=graph)

    source = MagicMock(
        thread_id=source_id,
        agent_id="agt_1",
        title="Original title",
        model_ref="openai/gpt-4o",
        reasoning_mode="auto",
        reasoning_effort=None,
    )
    created: dict[str, Any] = {}

    async def rebind(**kwargs: Any) -> None:
        created["rebind"] = kwargs

    registry = MagicMock()
    registry.create_thread.return_value = "thr_fork"
    registry.get_thread.return_value = MagicMock(
        title="Original title",
        last_active=9,
        created_at=8,
    )
    registry.rebind = rebind
    metadata_repo = MagicMock()

    out = await fork_dashboard_thread(
        thread_registry=registry,
        harness=harness,
        source=source,
        user_id=7,
        message_id="a1",
        content="ok",
        assistant_turns_from_end=2,
        conversation_metadata_repo=metadata_repo,
    )

    assert out["thread_id"] == "thr_fork"
    metadata_repo.record_fork.assert_called_once_with(7, "thr_fork", source_id)
    assert out["source_thread_id"] == source_id
    assert out["copied_messages"] == 2
    assert [m.id for m in store["thr_fork"]] == ["h1", "a1"]
    registry.update_title.assert_called_once_with("thr_fork", "Original title (fork)")
    registry.touch_last_active.assert_not_called()
    registry.update_composer.assert_called_once()
    assert created["rebind"]["thread_id"] == "thr_fork"
    assert created["rebind"]["session_key"] == ThreadRegistry.dashboard_key(
        agent_id="agt_1", user_id=7
    )


@pytest.mark.asyncio
async def test_fork_dashboard_thread_from_latest_assistant() -> None:
    source_id = "thr_src"
    messages = [
        HumanMessage(content="only", id="h1"),
        AIMessage(content="answer", id="a1"),
    ]
    store: dict[str, list[Any]] = {source_id: list(messages)}
    graph = SimpleNamespace()

    async def aget_state(config: dict[str, Any]) -> SimpleNamespace:
        tid = config["configurable"]["thread_id"]
        return SimpleNamespace(values={"messages": list(store.get(tid, []))})

    async def aupdate_state(config: dict[str, Any], values: dict[str, Any], **_k: Any) -> None:
        tid = config["configurable"]["thread_id"]
        store.setdefault(tid, []).extend(list(values.get("messages") or []))

    graph.aget_state = aget_state
    graph.aupdate_state = aupdate_state
    harness = SimpleNamespace(graph=graph)

    registry = MagicMock()
    registry.create_thread.return_value = "thr_fork"
    registry.get_thread.return_value = MagicMock(title="only", last_active=0, created_at=1)
    registry.rebind = AsyncMock()

    out = await fork_dashboard_thread(
        thread_registry=registry,
        harness=harness,
        source=MagicMock(
            thread_id=source_id,
            agent_id="agt_1",
            title="only",
            model_ref=None,
            reasoning_mode=None,
            reasoning_effort=None,
        ),
        user_id=1,
        assistant_turns_from_end=1,
    )

    assert out["copied_messages"] == 2
    assert [m.id for m in store["thr_fork"]] == ["h1", "a1"]
    registry.update_title.assert_called_once()


@pytest.mark.asyncio
async def test_fork_dashboard_thread_deletes_row_when_write_fails() -> None:
    source_id = "thr_src"
    messages = [
        HumanMessage(content="first", id="h1"),
        AIMessage(content="ok", id="a1"),
        HumanMessage(content="second", id="h2"),
        AIMessage(content="later", id="a2"),
    ]
    graph = SimpleNamespace()

    async def aget_state(_config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(values={"messages": list(messages)})

    graph.aget_state = aget_state
    graph.aupdate_state = AsyncMock(side_effect=RuntimeError("checkpoint write failed"))
    harness = SimpleNamespace(graph=graph)
    registry = MagicMock()
    registry.create_thread.return_value = "thr_fork"
    registry.rebind = AsyncMock()

    with pytest.raises(RuntimeError, match="checkpoint write failed"):
        await fork_dashboard_thread(
            thread_registry=registry,
            harness=harness,
            source=MagicMock(
                thread_id=source_id,
                agent_id="agt_1",
                title="t",
                model_ref=None,
                reasoning_mode=None,
                reasoning_effort=None,
            ),
            user_id=1,
            message_id="a2",
            assistant_turns_from_end=1,
        )

    registry.delete_thread.assert_called_once_with("thr_fork")


@pytest.mark.asyncio
@pytest.mark.parametrize("archive_enabled", [None, False, True])
@pytest.mark.parametrize("answer_index", [1, 5])
@pytest.mark.parametrize("with_ids", [False, True])
async def test_fork_preserves_ready_history_after_checkpoint_compaction(
    tmp_path: Path, archive_enabled: bool | None, answer_index: int, with_ids: bool
) -> None:
    from langchain_core.messages import messages_from_dict

    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import SqlitePool
    from octop.infra.db.services import RepoBundle
    from octop.infra.history.projection import message_inputs
    from octop.infra.history.reader import read_page
    from octop.infra.history.service import HistoryArchive
    from octop.infra.history.store import HistoryStore

    pool = SqlitePool(tmp_path / "state.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin")
    repos.agent_repo.create(agent_id="agent", user_id=owner, name="Agent")
    registry = ThreadRegistry(session_repo=repos.session_repo, thread_repo=repos.thread_repo)
    source_id = registry.create_thread(
        agent_id="agent",
        user_id=owner,
        channel_type="dashboard",
        session_key=ThreadRegistry.dashboard_key(agent_id="agent", user_id=owner),
    )
    source = registry.get_thread(source_id)
    assert source is not None
    messages = [
        HumanMessage(content="first question", id="h1" if with_ids else None),
        AIMessage(content="first answer", id="a1" if with_ids else None),
        HumanMessage(content="second question", id="h2" if with_ids else None),
        AIMessage(content="second answer", id="a2" if with_ids else None),
        HumanMessage(content="third question", id="h3" if with_ids else None),
        AIMessage(content="third answer", id="a3" if with_ids else None),
    ]
    repos.thread_message_repo.replace_all(source_id, message_inputs(messages))
    graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"messages": messages[-2:]})),
        aupdate_state=AsyncMock(),
    )
    harness = SimpleNamespace(graph=graph)
    store = (
        HistoryStore(tmp_path / "archive.db", identity="fork-test")
        if archive_enabled is not None
        else None
    )
    archive = (
        HistoryArchive(
            store,
            repos.thread_message_repo,
            repos.trajectory_event_repo,
            enabled=bool(archive_enabled),
        )
        if store is not None
        else None
    )
    try:
        selected = messages[answer_index]
        out = await fork_dashboard_thread(
            thread_registry=registry,
            harness=harness,
            source=source,
            user_id=owner,
            message_id=selected.id,
            assistant_turns_from_end=(len(messages) - answer_index + 1) // 2,
            thread_message_repo=repos.thread_message_repo,
            history_archive=archive,
        )
        expected = messages[: answer_index + 1]
        assert out["copied_messages"] == len(expected)
        written = graph.aupdate_state.call_args.args[1]["messages"]
        assert written == expected
        page = await read_page(
            archive,
            SimpleNamespace(get_agent=lambda _: harness),
            "agent",
            out["thread_id"],
            limit=100,
            messages=repos.thread_message_repo,
        )
        assert messages_from_dict(page["messages"]) == expected
        assert repos.thread_message_repo.head(source_id) == len(messages)
        graph.aget_state.assert_not_awaited()
    finally:
        if store is not None:
            store.close()
        pool.close()


@pytest.mark.asyncio
async def test_fork_uses_checkpoint_when_ready_projection_is_empty() -> None:
    from octop.infra.db.repos.thread_messages import ThreadMessageRepo

    messages = [HumanMessage(content="question", id="h1"), AIMessage(content="answer", id="a1")]
    graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={"messages": messages})),
        aupdate_state=AsyncMock(),
    )
    projection = MagicMock(spec=ThreadMessageRepo)
    projection.projection_status.return_value = "ready"
    projection.head.return_value = 0
    projection.range_rows.return_value = []
    registry = MagicMock()
    registry.create_thread.return_value = "thr_fork"
    registry.rebind = AsyncMock()
    out = await fork_dashboard_thread(
        thread_registry=registry,
        harness=SimpleNamespace(graph=graph),
        source=MagicMock(thread_id="source", agent_id="agent", title="Title"),
        user_id=1,
        assistant_turns_from_end=1,
        thread_message_repo=projection,
    )
    assert out["copied_messages"] == 2
    assert graph.aupdate_state.call_args.args[1]["messages"] == messages
    graph.aget_state.assert_awaited_once()
    assert projection.append_if_ready.call_args_list[0].args[0] == "source"
