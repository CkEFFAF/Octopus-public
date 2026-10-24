from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from octop.infra.conversations.generation import MetadataInputBudgetError, generate_json
from octop.infra.conversations.models import GeneratedBrief, GeneratedTitle
from octop.infra.utils.model_diagnostics import safe_diagnostics


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locale,language,too_long",
    [
        ("zh", "Simplified Chinese (简体中文)", False),
        ("en", "English", False),
        ("zh", "Simplified Chinese (简体中文)", True),
    ],
)
async def test_auxiliary_call_is_tool_free_account_scoped_and_records_usage(
    monkeypatch, locale, language, too_long
):
    calls, recorded, closed = [], [], []

    class Model:
        profile = {"max_input_tokens": 16000, "max_output_tokens": 4096, "context_window": 20000}

        def bind(self, **kwargs):
            assert kwargs == {"max_tokens": 3200, "timeout": 30}
            return self

        async def ainvoke(self, messages, config):
            calls.append(messages)
            assert config == {"callbacks": []}
            assert "untrusted DATA" in messages[0].content
            assert f"human-readable values in {language}" in messages[0].content
            assert "never a snake_case identifier" in messages[0].content
            return AIMessage(
                content='{"one_liner":"summary","objective":"goal"}',
                usage_metadata={"input_tokens": 120, "output_tokens": 20, "total_tokens": 140},
            )

    class Factory:
        def __init__(self, configs):
            assert configs == ["owner-only"]

        def get_chat_model(self, ref):
            assert ref == "owner/model"
            return Model()

        async def aclose(self):
            closed.append(True)

    store = SimpleNamespace(
        is_model_ref_usable=lambda ref: ref == "owner/model",
        build_harness_configs=lambda: ["owner-only"],
        get_model_reasoning_capability=lambda ref: None,
    )
    manager = SimpleNamespace(
        providers_for_user=lambda owner: store if owner == 7 else None,
        _repos=SimpleNamespace(
            usage_repo=SimpleNamespace(record=lambda **kwargs: recorded.append(kwargs)),
            user_repo=SimpleNamespace(get=lambda owner: SimpleNamespace(locale=locale)),
        ),
    )
    monkeypatch.setattr("octop.infra.conversations.generation.ChatModelFactory", Factory)
    job = {"owner_user_id": 7, "agent_id": "agent", "thread_id": "thread"}
    request = generate_json(
        manager,
        job,
        "owner/model",
        {
            "messages": [
                {
                    "text": "会话整理" * (50000 if too_long else 2000),
                    "ref": {"kind": "message", "id": "1"},
                }
            ]
        },
        GeneratedBrief.model_json_schema(),
        "thread_brief",
    )
    if too_long:
        with pytest.raises(MetadataInputBudgetError) as error:
            await request
        assert error.value.input_tokens_estimate > error.value.input_limit_tokens
        assert calls == recorded == []
        assert closed == [True]
        return
    result = await request
    assert json.loads(result)["objective"] == "goal"
    assert recorded[0]["source"] == "thread_brief"
    assert recorded[0]["user_id"] == 7
    assert recorded[0]["input_tokens"] == 120
    assert len(calls) == len(closed) == 1


def test_input_budget_diagnostic_reports_only_sizes():
    diagnostic = safe_diagnostics(
        MetadataInputBudgetError(42000, 18000, 12000),
        code="METADATA_INPUT_BUDGET",
        stage="thread_brief",
        job_id="synthetic",
    )
    assert diagnostic["input_bytes"] == 42000
    assert diagnostic["input_tokens_estimate"] == 18000
    assert diagnostic["input_limit_tokens"] == 12000
    assert set(diagnostic) == {
        "code",
        "exception",
        "stage",
        "job_id",
        "input_bytes",
        "input_tokens_estimate",
        "input_limit_tokens",
    }


@pytest.mark.asyncio
async def test_openai_auxiliary_json_disables_optional_thinking_within_existing_budget(monkeypatch):
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(api_key="synthetic-test-only", model="synthetic")

    async def invoke(self, messages, config, **kwargs):
        assert kwargs["max_tokens"] == 3200
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kwargs["timeout"] == 30
        return AIMessage(content='{"title":"测试主题"}')

    monkeypatch.setattr(ChatOpenAI, "ainvoke", invoke)

    async def close():
        return None

    factory = SimpleNamespace(get_chat_model=lambda ref: model, aclose=close)
    monkeypatch.setattr(
        "octop.infra.conversations.generation.ChatModelFactory", lambda configs: factory
    )
    store = SimpleNamespace(
        is_model_ref_usable=lambda ref: True,
        build_harness_configs=lambda: [],
        get_model_reasoning_capability=lambda ref: {
            "adapter": "thinking",
            "toggle": True,
            "default_mode": "enabled",
        },
    )
    manager = SimpleNamespace(
        providers_for_user=lambda uid: store,
        _repos=SimpleNamespace(usage_repo=SimpleNamespace(record=lambda **kwargs: None)),
    )
    output = await generate_json(
        manager,
        {"owner_user_id": 1, "agent_id": "synthetic", "thread_id": "synthetic"},
        "provider/model",
        {"messages": [{"text": "虚构验收"}]},
        GeneratedTitle.model_json_schema(),
        "thread_title",
    )
    assert json.loads(output)["title"] == "测试主题"


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["thread_title", "thread_brief", "period_digest"])
async def test_auxiliary_json_does_not_enter_parent_chat_stream(monkeypatch, purpose):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.runnables.config import var_child_runnable_config
    from langgraph.graph import END, START, MessagesState, StateGraph

    metadata_json = '{"one_liner":"内部摘要","objective":"整理会话"}'
    model = FakeListChatModel(responses=[metadata_json])
    recorded, closed = [], []

    async def close():
        closed.append(True)

    monkeypatch.setattr(
        "octop.infra.conversations.generation.ChatModelFactory",
        lambda configs: SimpleNamespace(get_chat_model=lambda ref: model, aclose=close),
    )
    store = SimpleNamespace(
        is_model_ref_usable=lambda ref: True,
        build_harness_configs=lambda: [],
        get_model_reasoning_capability=lambda ref: None,
    )
    manager = SimpleNamespace(
        providers_for_user=lambda owner: store,
        _repos=SimpleNamespace(usage_repo=SimpleNamespace(record=lambda **kw: recorded.append(kw))),
    )

    async def reply(state):
        parent = var_child_runnable_config.get()
        output = await generate_json(
            manager,
            {"owner_user_id": 7, "agent_id": "agent", "thread_id": "thread"},
            "owner/model",
            {"messages": [{"text": "实验到哪了"}]},
            GeneratedBrief.model_json_schema(),
            purpose,
        )
        assert output == metadata_json
        assert var_child_runnable_config.get() is parent
        return {"messages": [AIMessage(content="实验已完成三组对照。", id="normal-answer")]}

    graph = StateGraph(MessagesState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    streamed = [
        message.content
        async for message, _ in graph.compile().astream({"messages": []}, stream_mode="messages")
    ]
    assert streamed == ["实验已完成三组对照。"]
    assert recorded[0]["source"] == purpose
    assert closed == [True]
