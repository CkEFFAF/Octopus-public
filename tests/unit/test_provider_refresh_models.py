"""Unit tests for provider refresh-models merge + persistence (0036 S0)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from octop.infra.agents.providers.refresh import (
    merge_models_with_source,
    refresh_provider_models,
    remote_list_supported,
)


def test_remote_list_supported_openai_only() -> None:
    assert remote_list_supported("openai") is True
    assert remote_list_supported("anthropic") is False
    assert remote_list_supported("bedrock") is False


def test_merge_never_deletes_user_only_and_tags_source() -> None:
    current = [
        {"id": "my-custom-model", "name": "Mine", "enabled": True},
        {"id": "gpt-old", "name": "gpt-old", "enabled": True},
    ]
    fetched = [{"id": "gpt-x", "name": "gpt-x"}, {"id": "gpt-old", "name": "gpt-old"}]
    presets = [
        {
            "id": "deepseek-flash",
            "name": "DeepSeek Flash",
            "input": ["text"],
            "context_window": 1000,
        }
    ]
    merged, stats = merge_models_with_source(current, fetched, presets)
    by_id = {m["id"]: m for m in merged}
    assert by_id["my-custom-model"]["source"] == "user"
    assert by_id["my-custom-model"]["enabled"] is True
    assert by_id["gpt-x"]["source"] == "remote"
    assert by_id["gpt-x"]["enabled"] is False
    assert by_id["gpt-old"]["source"] == "remote"
    assert by_id["deepseek-flash"]["source"] == "preset"
    assert by_id["deepseek-flash"]["enabled"] is False
    assert {"id": "my-custom-model"} in stats["kept_user"]
    assert any(a["id"] == "gpt-x" for a in stats["added"])


def test_merge_preserves_user_limits_and_enriches_empty_fields() -> None:
    current = [
        {
            "id": "m1",
            "name": "自定义",
            "enabled": True,
            "thinking": False,
            "context_window": 111,
            "max_tokens": 22,
        }
    ]
    presets = [
        {
            "id": "m1",
            "name": "Official",
            "input": ["text", "image"],
            "context_window": 999,
            "max_output_tokens": 50,
            "reasoning": True,
        }
    ]
    merged, stats = merge_models_with_source(current, [{"id": "m1"}], presets)
    m = merged[0]
    assert m["name"] == "自定义"
    assert m["enabled"] is True
    assert m["thinking"] is False
    assert m["context_window"] == 111
    assert m["max_tokens"] == 22
    assert m["max_output_tokens"] == 50
    assert m["input"] == ["text", "image"]
    assert m["source"] == "remote"
    assert stats["enriched"] == 1


def _mock_server(row: Any, *, update: MagicMock | None = None) -> Any:
    repo = MagicMock()
    repo.get.return_value = row
    repo.update = update or MagicMock()
    services = SimpleNamespace(
        provider_repo=repo,
        agent_repo=MagicMock(),
        settings_repo=MagicMock(),
    )
    return SimpleNamespace(services=services, app_runtime=None)


def _row(**kwargs: Any) -> Any:
    defaults = {
        "id": 12,
        "user_id": 1,
        "name": "OpenAI",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "models_json": "[]",
        "get_models": lambda: [],
    }
    defaults.update(kwargs)
    row = SimpleNamespace(**defaults)
    if "get_models" not in kwargs and "models" in kwargs:
        models = kwargs["models"]
        row.get_models = lambda: list(models)  # type: ignore[method-assign]
    return row


@pytest.mark.asyncio
async def test_refresh_openai_remote_writes_models() -> None:
    row = _row(models=[{"id": "my-custom-model", "name": "Mine", "enabled": True}])
    update = MagicMock()
    server = _mock_server(row, update=update)
    remote = {
        "ok": True,
        "models": [{"id": "gpt-x", "name": "gpt-x"}, {"id": "gpt-4o", "name": "gpt-4o"}],
    }
    preset = {
        "id": "openai",
        "name": "OpenAI",
        "models": [{"id": "gpt-4o", "name": "GPT-4o", "input": ["text"]}],
    }
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=AsyncMock(return_value=remote),
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch(
            "octop.infra.agents.providers.refresh.clear_stale_pins_for_provider",
        ),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    assert result["source_used"] == "remote+preset"
    assert result["remote_supported"] is True
    update.assert_called_once()
    kwargs = update.call_args.kwargs
    assert "models_json" in kwargs
    assert "my-custom-model" in kwargs["models_json"]
    assert "gpt-x" in kwargs["models_json"]


@pytest.mark.asyncio
async def test_refresh_remote_failure_without_preset_does_not_write() -> None:
    row = _row(models=[{"id": "keep", "name": "Keep", "enabled": True}])
    update = MagicMock()
    server = _mock_server(row, update=update)
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=AsyncMock(return_value={"ok": False, "error": "upstream 5xx"}),
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=None,
        ),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is False
    assert "5xx" in (result["error"] or "") or "upstream" in (result["error"] or "")
    update.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_anthropic_uses_preset_only() -> None:
    row = _row(
        kind="anthropic",
        name="Anthropic",
        api_key="sk-ant",
        models=[],
    )
    update = MagicMock()
    server = _mock_server(row, update=update)
    preset = {
        "id": "anthropic",
        "name": "Anthropic",
        "models": [{"id": "claude-sonnet-4", "name": "Claude Sonnet 4"}],
    }
    fetch = AsyncMock()
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=fetch,
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch("octop.infra.agents.providers.refresh.clear_stale_pins_for_provider"),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    assert result["source_used"] == "preset"
    assert result["remote_supported"] is False
    fetch.assert_not_awaited()
    update.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_openai_without_key_falls_back_to_preset() -> None:
    row = _row(api_key="", models=[])
    update = MagicMock()
    server = _mock_server(row, update=update)
    preset = {
        "id": "openai",
        "name": "OpenAI",
        "models": [{"id": "gpt-4o", "name": "GPT-4o"}],
    }
    fetch = AsyncMock()
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=fetch,
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch("octop.infra.agents.providers.refresh.clear_stale_pins_for_provider"),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    assert result["source_used"] == "preset"
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_go_keeps_remote_ids_absent_from_preset() -> None:
    """0036.1 AC-001: omen-alpha / gemini-4-argon / minimax flash not dropped."""
    row = _row(
        name="OpenCode Go (Compatible)",
        base_url="https://opencode.ai/inference/go/openai/v1",
        models=[{"id": "my-custom-model", "name": "Mine", "enabled": True}],
    )
    update = MagicMock()
    server = _mock_server(row, update=update)
    remote = {
        "ok": True,
        "models": [
            {"id": "omen-alpha", "name": "omen-alpha"},
            {"id": "gemini-4-argon-contributor", "name": "gemini-4-argon-contributor"},
            {"id": "minimax-m3.1-flash-free", "name": "minimax-m3.1-flash-free"},
            {"id": "mimo-v2.6-pro", "name": "mimo-v2.6-pro"},
        ],
    }
    # Preset deliberately omits the three "new" remote ids.
    preset = {
        "id": "opencode-go-openai",
        "name": "OpenCode Go (Compatible)",
        "models": [
            {
                "id": "mimo-v2.6-pro",
                "name": "MiMo V2.6 Pro",
                "input": ["text"],
                "context_window": 1000,
            }
        ],
    }
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=AsyncMock(return_value=remote),
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch(
            "octop.infra.agents.providers.refresh.enrich_models_from_upstream",
            new=AsyncMock(side_effect=lambda models, provider_key=None: (models, 0)),
        ),
        patch("octop.infra.agents.providers.refresh.clear_stale_pins_for_provider"),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    by_id = {m["id"]: m for m in result["models"]}
    for mid in (
        "omen-alpha",
        "gemini-4-argon-contributor",
        "minimax-m3.1-flash-free",
    ):
        assert mid in by_id
        assert by_id[mid]["source"] == "remote"
        assert by_id[mid]["enabled"] is False
    assert by_id["my-custom-model"]["source"] == "user"
    assert "my-custom-model" in update.call_args.kwargs["models_json"]


@pytest.mark.asyncio
async def test_refresh_models_dev_failure_still_persists_remote_ids() -> None:
    """0036.1 AC-004: models.dev down must not block writing remote ids."""
    row = _row(
        name="OpenCode Go (Compatible)",
        base_url="https://opencode.ai/inference/go/openai/v1",
        models=[],
    )
    update = MagicMock()
    server = _mock_server(row, update=update)
    remote = {
        "ok": True,
        "models": [{"id": "omen-alpha", "name": "omen-alpha"}],
    }
    preset = {
        "id": "opencode-go-openai",
        "name": "OpenCode Go (Compatible)",
        "models": [],
    }

    async def _boom(models, provider_key=None):
        # Simulate unexpected failure path; enrich should still degrade.
        raise RuntimeError("models.dev exploded")

    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=AsyncMock(return_value=remote),
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch(
            "octop.infra.agents.providers.refresh.enrich_models_from_upstream",
            new=AsyncMock(side_effect=_boom),
        ),
        patch("octop.infra.agents.providers.refresh.clear_stale_pins_for_provider"),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    assert result["upstream_enriched"] == 0
    assert any(m["id"] == "omen-alpha" for m in result["models"])
    update.assert_called_once()
    assert "omen-alpha" in update.call_args.kwargs["models_json"]


@pytest.mark.asyncio
async def test_refresh_enriches_empty_fields_from_models_dev() -> None:
    """0036.1 AC-003: empty fields filled from models.dev when reachable."""
    from octop.infra.agents.providers import upstream_catalog as uc

    row = _row(
        name="OpenCode Go (Compatible)",
        base_url="https://opencode.ai/inference/go/openai/v1",
        models=[],
    )
    update = MagicMock()
    server = _mock_server(row, update=update)
    remote = {
        "ok": True,
        "models": [{"id": "gemini-4-argon-contributor", "name": "gemini-4-argon-contributor"}],
    }
    preset = {
        "id": "opencode-go-openai",
        "name": "OpenCode Go (Compatible)",
        "models": [],
    }
    catalog = {
        "opencode-go": {
            "models": {
                "gemini-4-argon-contributor": {
                    "id": "gemini-4-argon-contributor",
                    "name": "Gemini 4 Argon Contributor",
                    "reasoning": True,
                    "modalities": {"input": ["text", "image"]},
                    "limit": {"context": 1048576, "output": 65536},
                }
            }
        }
    }
    uc.reset_upstream_catalog_cache()
    with (
        patch(
            "octop.infra.agents.providers.refresh.fetch_openai_compatible_models",
            new=AsyncMock(return_value=remote),
        ),
        patch(
            "octop.infra.agents.providers.refresh.match_provider_preset",
            return_value=preset,
        ),
        patch(
            "octop.infra.agents.providers.upstream_catalog.fetch_models_dev_api",
            new=AsyncMock(return_value=catalog),
        ),
        patch("octop.infra.agents.providers.refresh.clear_stale_pins_for_provider"),
        patch(
            "octop.infra.agents.providers.refresh.is_local_runtime_provider",
            return_value=False,
        ),
    ):
        result = await refresh_provider_models(row=row, server=server, prefer="auto")

    assert result["ok"] is True
    assert result["upstream_enriched"] >= 1
    m = next(x for x in result["models"] if x["id"] == "gemini-4-argon-contributor")
    assert m["name"] == "Gemini 4 Argon Contributor"
    assert m["context_window"] == 1048576
    assert m["max_output_tokens"] == 65536
    assert m["input"] == ["text", "image"]
    assert m["reasoning"] is True
    assert m["source"] == "remote"
    assert m["enabled"] is False
