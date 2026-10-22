from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from octop.infra.conversations.generation import generate_json
from octop.infra.conversations.models import GeneratedBrief, GeneratedTitle


@pytest.mark.asyncio
async def test_auxiliary_call_is_tool_free_account_scoped_and_records_usage(monkeypatch):
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
            usage_repo=SimpleNamespace(record=lambda **kwargs: recorded.append(kwargs))
        ),
    )
    monkeypatch.setattr("octop.infra.conversations.generation.ChatModelFactory", Factory)
    job = {"owner_user_id": 7, "agent_id": "agent", "thread_id": "thread"}
    result = await generate_json(
        manager,
        job,
        "owner/model",
        {"messages": [{"text": "会话整理" * 200, "ref": {"kind": "message", "id": "1"}}]},
        GeneratedBrief.model_json_schema(),
        "thread_brief",
    )
    assert json.loads(result)["objective"] == "goal"
    assert recorded[0]["source"] == "thread_brief"
    assert recorded[0]["user_id"] == 7
    assert recorded[0]["input_tokens"] == 120
    assert len(calls) == len(closed) == 1


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
