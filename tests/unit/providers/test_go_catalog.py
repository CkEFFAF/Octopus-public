"""0032: one effective Go catalog reaches owner APIs and the native clients."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from octop_harness.llm.factory import ChatModelFactory

from octop.api.routers.providers import _row_to_dict
from octop.infra.agents.providers.catalog import effective_provider_models
from octop.infra.agents.providers.resolved import list_resolved_models
from octop.infra.agents.providers.store import ProviderStore
from octop.infra.db.repos.providers import ProviderRow


def _row(models: list[dict[str, Any]] | None = None, **overrides: Any) -> ProviderRow:
    row = ProviderRow(
        id=7,
        user_id=1,
        name="OpenCode Go (Compatible)",
        kind="openai",
        base_url="https://opencode.ai/zen/go/v1",
        api_key="sk-test",
        extra_json=json.dumps({"headers": {"x-opencode-session": "saved", "X-Custom": "keep"}}),
        models_json=json.dumps(models if models is not None else [{"id": "deepseek-v4.1-flash"}]),
        note="keep",
        enabled=1,
        created_at=1,
        updated_at=1,
    )
    return replace(row, **overrides)


class _Repo:
    def __init__(self, row: ProviderRow) -> None:
        self.row = row

    def list_all(self, _user_id: int) -> list[ProviderRow]:
        return [self.row]

    def get_by_name(self, _user_id: int, name: str) -> ProviderRow | None:
        return self.row if name == self.row.name else None


def test_saved_go_catalog_is_selectable_in_api_resolution_and_runtime_without_db_writes() -> None:
    row = _row()
    before = row.models_json
    api_models = _row_to_dict(row)["models"]
    effective = effective_provider_models(row)
    assert [m["id"] for m in api_models] == [m["id"] for m in effective]
    assert effective[0]["id"] == "deepseek-v4.1-flash"
    new = next(m for m in effective if m["id"] == "mimo-v2.6-pro")
    assert new["enabled"] is True
    assert new.get("use_responses_api", False) is False
    assert "mimo-v2.6-pro" in {m["model"] for m in list_resolved_models([row])}
    store = ProviderStore(_Repo(row), row.user_id)  # type: ignore[arg-type]
    config = store.build_harness_configs()[0]
    assert config.get_model("mimo-v2.6-pro") is not None
    assert store.is_model_ref_usable(f"{row.name}/mimo-v2.6-pro")
    assert store.resolve_first_model_ref() == f"{row.name}/deepseek-v4.1-flash"
    assert config.base_url == row.base_url
    assert config.api_key == row.api_key
    assert config.headers == {"x-opencode-session": "saved", "X-Custom": "keep"}
    assert row.models_json == before


def test_existing_overrides_disabled_and_custom_models_keep_order_and_values() -> None:
    saved: list[dict[str, Any]] = [
        {"id": "private", "name": "My default", "enabled": True, "custom": {"keep": 1}},
        {
            "id": "mimo-v2.6-pro",
            "name": "My MiMo",
            "enabled": False,
            "input": ["text"],
            "context_window": 0,
            "max_output_tokens": 0,
            "max_tokens": 0,
            "reasoning": False,
            "thinking": False,
            "use_responses_api": False,
        },
        {"id": "grok-4.7", "enabled": True, "use_responses_api": False},
    ]
    row = _row(saved)
    effective = effective_provider_models(row)
    assert [m["id"] for m in effective[:3]] == [m["id"] for m in saved]
    for original, merged in zip(saved, effective, strict=False):
        assert all(merged[key] == value for key, value in original.items())
    assert "max_input_tokens" not in effective[1]
    assert "reasoning_config" not in effective[1]
    assert _row_to_dict(row)["models"][1]["reasoning"] is False
    assert "mimo-v2.6-pro" not in {m["model"] for m in list_resolved_models([row])}
    assert effective_provider_models(row) == effective
    assert json.loads(row.models_json or "[]") == saved


@pytest.mark.parametrize("context_key", ["context_window", "max_input_tokens"])
def test_explicit_zero_limits_and_reasoning_disable_reach_runtime(context_key: str) -> None:
    row = _row(
        [
            {
                "id": "deepseek-v4.1-flash",
                context_key: 0,
                "max_output_tokens": 0,
                "input": ["text"],
                "reasoning": False,
                "thinking": False,
            }
        ]
    )
    resolved = list_resolved_models([row])[0]
    assert resolved["context_window"] == 0
    assert resolved["max_output_tokens"] == 0
    assert resolved["reasoning"] is False
    model = ProviderStore(_Repo(row), 1).build_harness_configs()[0].models[0]  # type: ignore[arg-type]
    assert model.context_window == model.max_input_tokens == model.max_output_tokens == 0
    assert model.input == ["text"]
    assert model.thinking is False


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "My Go"},
        {"name": "OpenCode Zen (Compatible)"},
        {"name": "opencode-zen-openai"},
        {"kind": "anthropic"},
        {"base_url": "https://opencode.ai/zen/v1"},
        {"base_url": "https://proxy.example/go/v1"},
        {"base_url": "https://proxy.opencode.ai/inference/go/v1"},
        {"base_url": "https://opencode.ai/inference/go/v1?custom=true"},
    ],
)
def test_does_not_expand_zen_custom_or_protocol_mismatches(changes: dict[str, Any]) -> None:
    row = _row(**changes)
    assert effective_provider_models(row) == row.get_models()


@pytest.mark.parametrize(
    "name,kind,base_url",
    [
        ("opencode-go-openai", "openai", "https://opencode.ai/inference/go/openai/v1"),
        ("OpenCode Go (Compatible)", "openai", "https://opencode.ai/inference/go/v1/"),
        ("opencode-go-anthropic", "anthropic", "https://opencode.ai/zen/go"),
        ("OpenCode Go (Anthropic)", "anthropic", "https://opencode.ai/inference/go/anthropic"),
    ],
)
def test_expands_only_matching_go_variant(name: str, kind: str, base_url: str) -> None:
    models = effective_provider_models(_row([], name=name, kind=kind, base_url=base_url))
    ids = [m["id"] for m in models]
    assert len(ids) == len(set(ids))
    assert ("mimo-v2.6-pro" in ids) is (kind == "openai")
    assert ("claude-haiku-5-5" in ids) is (kind == "anthropic")
    assert "gemini-4-argon-contributor" not in ids


@pytest.mark.parametrize(
    "model_id,path",
    [
        ("mimo-v2.6-pro", "/inference/go/openai/v1/chat/completions"),
        ("mimo-v2.6-flash", "/inference/go/openai/v1/chat/completions"),
        ("grok-4.7", "/inference/go/openai/v1/responses"),
    ],
)
def test_effective_models_reach_the_native_sdk_route(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
    path: str,
) -> None:
    row = _row(base_url="https://opencode.ai/inference/go/openai/v1")
    provider = ProviderStore(_Repo(row), 1).build_harness_configs()[0]  # type: ignore[arg-type]
    requests: list[httpx.Request] = []

    def send(_client: httpx.Client, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        requests.append(request)
        if path.endswith("/responses"):
            body = {
                "id": "resp-test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": model_id,
                "output": [
                    {
                        "type": "message",
                        "id": "msg-test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                    }
                ],
            }
        else:
            body = {
                "id": "chat-test",
                "object": "chat.completion",
                "created": 1,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            }
        return httpx.Response(200, request=request, json=body)

    monkeypatch.setattr(httpx.Client, "send", send)
    factory = ChatModelFactory([provider])
    try:
        assert factory.get_chat_model(f"{row.name}/{model_id}").invoke("ping").text == "ok"
    finally:
        factory.close()
    assert len(requests) == 1
    assert requests[0].url.path == path
    assert json.loads(requests[0].content)["model"] == model_id
    assert requests[0].headers["x-opencode-session"] == "saved"
