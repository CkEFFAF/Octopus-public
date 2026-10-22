"""Public model discovery remains fresh without mutating saved credentials."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from octop.infra.agents.providers import live_catalog as catalog


@pytest.mark.asyncio
async def test_refresh_ttl_force_and_failure_keep_last_good(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "_loaded_path", "test")
    monkeypatch.setattr(catalog, "_snapshot", {})
    monkeypatch.setattr(catalog, "snapshot", lambda: catalog._snapshot)
    monkeypatch.setattr(
        catalog.PathLayout, "from_env", lambda: type("Layout", (), {"root": tmp_path})()
    )
    clock = [100000.0]
    monkeypatch.setattr(catalog.time, "time", lambda: clock[0])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = [
        httpx.Response(
            200,
            json={"opencode-go": {"models": {"new-free": {"id": "new-free"}}}},
            request=httpx.Request("GET", "https://example.test"),
        ),
        httpx.Response(
            200,
            json={"data": [{"id": "new-free"}]},
            request=httpx.Request("GET", "https://example.test"),
        ),
    ]
    with patch.object(catalog.httpx, "AsyncClient", return_value=client):
        await catalog.refresh_catalog()
        assert client.get.await_count == 2
        await catalog.refresh_catalog()
        assert client.get.await_count == 2
        cache = tmp_path / "cache/provider-catalog.json"
        saved = cache.read_bytes()
        clock[0] += 61
        client.get.side_effect = httpx.ConnectError("secret upstream error")
        result = await catalog.refresh_catalog(force=True)
        assert client.get.await_count == 4
        assert all(row["error"] == "CATALOG_REFRESH_FAILED" for row in result["sources"])
        assert catalog._snapshot["opencode-go"]["data"]["data"][0]["id"] == "new-free"
        assert b"secret" not in cache.read_bytes()
        assert saved != cache.read_bytes()


def test_go_discovery_without_metadata_adds_new_ids_and_keeps_endpoint(monkeypatch):
    monkeypatch.setattr(
        catalog, "snapshot", lambda: {"opencode-go": {"data": {"data": [{"id": "new-free"}]}}}
    )
    presets = [
        {"id": "opencode-go-openai", "protocol": "openai", "base_url": "custom", "models": []}
    ]
    result = catalog.overlay_presets(presets)
    assert result[0]["base_url"] == "custom"
    assert result[0]["models"][0]["id"] == "new-free"


def test_protocol_boundaries_and_explicit_adapters_are_preserved(monkeypatch):
    rows = {
        "fresh": {"provider": {"api": "https://go/openai/v1", "npm": "@ai-sdk/openai"}},
        "existing": {"provider": {"npm": "@ai-sdk/openai"}},
        "claude-new": {"provider": {"api": "https://go/anthropic/v1"}},
        "gemini-new": {"provider": {"api": "https://go/google/v1"}},
    }
    monkeypatch.setattr(
        catalog,
        "snapshot",
        lambda: {
            "models.dev": {"data": {"opencode-go": {"models": rows}}},
            "opencode-go": {
                "data": {
                    "data": [
                        {"id": mid}
                        for mid in [*rows, "claude-unknown", "gemini-unknown", "new-free"]
                    ]
                }
            },
        },
    )
    presets = [
        {
            "id": "opencode-go-openai",
            "protocol": "openai",
            "models": [{"id": "existing", "use_responses_api": False}],
        },
        {"id": "opencode-go-anthropic", "protocol": "anthropic", "models": []},
    ]
    result = catalog.overlay_presets(presets)
    models = {row["id"]: row for row in result[0]["models"]}
    assert set(models) == {"fresh", "existing", "new-free"}
    assert models["fresh"]["use_responses_api"] is True
    assert models["existing"]["use_responses_api"] is False
    assert [row["id"] for row in result[1]["models"]] == ["claude-new"]


@pytest.mark.asyncio
async def test_invalid_upstream_shape_reports_failure_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "snapshot", lambda: {})
    monkeypatch.setattr(
        catalog.PathLayout, "from_env", lambda: type("Layout", (), {"root": tmp_path})()
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(
        200, json={"opencode-go": []}, request=httpx.Request("GET", "https://example.test")
    )
    with patch.object(catalog.httpx, "AsyncClient", return_value=client):
        await catalog.refresh_catalog(force=True)
    assert client.get.await_count == 2
