"""Public model metadata snapshots; never send account credentials upstream."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import httpx

from octop.infra.utils.paths import PathLayout

SOURCES = {
    "models.dev": "https://models.dev/api.json",
    "opencode-go": "https://opencode.ai/zen/go/v1/models",
    "opencode-zen": "https://opencode.ai/inference/v1/models",
    "free-models-hub": "https://free-api.gd7.cn/api/models",
}
logger = logging.getLogger(__name__)
TTL = 86400
_lock = asyncio.Lock()
_snapshot: dict[str, Any] = {}
_loaded_path: str = ""


def snapshot() -> dict[str, Any]:
    global _snapshot, _loaded_path
    path = PathLayout.from_env().root / "cache" / "provider-catalog.json"
    if str(path) != _loaded_path:
        _loaded_path = str(path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            _snapshot = (
                {
                    name: row
                    for name, row in value.items()
                    if name in SOURCES
                    and isinstance(row, dict)
                    and isinstance(row.get("updated_at", 0), (int, float))
                    and isinstance(row.get("checked_at", 0), (int, float))
                    and isinstance(row.get("data", {}), dict)
                }
                if isinstance(value, dict)
                else {}
            )
        except (OSError, ValueError):
            _snapshot = {}
    return _snapshot


def catalog_status() -> dict[str, Any]:
    data = snapshot()
    return {
        "sources": [
            {
                "name": name,
                "url": url,
                "updated_at": data.get(name, {}).get("updated_at"),
                "error": data.get(name, {}).get("error"),
                "stale": time.time() - data.get(name, {}).get("updated_at", 0) > TTL,
            }
            for name, url in SOURCES.items()
        ]
    }


async def refresh_catalog(*, force: bool = False) -> dict[str, Any]:
    async with _lock:
        data = snapshot()
        changed = False
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers={"User-Agent": "octop/provider-catalog"}
        ) as client:
            for name, url in SOURCES.items():
                previous = data.get(name, {})
                interval = 60 if force else 3600 if previous.get("error") else TTL
                if time.time() - previous.get("checked_at", 0) < interval:
                    continue
                changed = True
                checked = time.time()
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    if len(response.content) > 30_000_000:
                        raise ValueError("catalog too large")
                    payload = response.json()
                    if name == "models.dev":
                        if (
                            not isinstance(payload, dict)
                            or not isinstance(payload.get("opencode-go"), dict)
                            or not isinstance(payload["opencode-go"].get("models"), dict)
                            or not payload["opencode-go"]["models"]
                        ):
                            raise ValueError("invalid model catalog")
                    elif name == "free-models-hub":
                        if (
                            not isinstance(payload, dict)
                            or payload.get("ok") is not True
                            or not isinstance(payload.get("items"), list)
                        ):
                            raise ValueError("invalid free leaderboard")
                        pages = int(payload.get("total_pages", 1))
                        if not 1 <= pages <= 50:
                            raise ValueError("free leaderboard too large")
                        for page in range(2, pages + 1):
                            part = await client.get(url, params={"page": page})
                            part.raise_for_status()
                            more = part.json()
                            if more.get("ok") is not True or not isinstance(
                                more.get("items"), list
                            ):
                                raise ValueError("incomplete free leaderboard")
                            payload["items"].extend(more["items"])
                    elif (
                        not isinstance(payload, dict)
                        or not isinstance(payload.get("data"), list)
                        or not payload["data"]
                    ):
                        raise ValueError("invalid Go catalog")
                    data[name] = {"updated_at": checked, "checked_at": checked, "data": payload}
                except (httpx.HTTPError, ValueError):
                    data[name] = {
                        **previous,
                        "checked_at": checked,
                        "error": "CATALOG_REFRESH_FAILED",
                    }
        if changed:
            path = PathLayout.from_env().root / "cache" / "provider-catalog.json"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, path)
            except OSError:
                logger.warning("Provider catalog disk cache could not be saved")
        return catalog_status()


def _model(value: dict[str, Any]) -> dict[str, Any]:
    limits = value.get("limit")
    if not isinstance(limits, dict):
        limits = {}
    modalities = value.get("modalities")
    if not isinstance(modalities, dict):
        modalities = {}
    result: dict[str, Any] = {
        "id": value["id"],
        "name": value.get("name") or value["id"],
        "input": modalities.get("input", ["text"]),
        "reasoning": bool(value.get("reasoning")),
        "enabled": True,
    }
    for source, dest in (
        ("context", "context_window"),
        ("input", "max_input_tokens"),
        ("output", "max_output_tokens"),
    ):
        if isinstance(limits.get(source), int) and limits[source] > 0:
            result[dest] = limits[source]
    return result


def is_free_zen_model(mid: str) -> bool:
    metadata = snapshot().get("models.dev", {}).get("data", {}).get("opencode", {})
    models = metadata.get("models", {}) if isinstance(metadata, dict) else {}
    meta = models.get(mid, {}) if isinstance(models, dict) else {}
    if not isinstance(meta, dict) or meta.get("status") == "deprecated":
        return False
    cost = meta.get("cost", {})
    return (
        mid.endswith("-free")
        or mid == "big-pickle"
        or (isinstance(cost, dict) and cost.get("input") == 0 and cost.get("output") == 0)
    )


def overlay_presets(presets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data = snapshot()
    registry = data.get("models.dev", {}).get("data", {})
    go_rows = data.get("opencode-go", {}).get("data", {}).get("data")
    go_ids = (
        {row["id"] for row in go_rows if isinstance(row, dict) and isinstance(row.get("id"), str)}
        if isinstance(go_rows, list) and go_rows
        else None
    )
    for preset in presets:
        identity = preset["id"]
        if identity == "opencode-zen-free":
            rows = data.get("opencode-zen", {}).get("data", {}).get("data", [])
            metadata = registry.get("opencode", {}).get("models", {})
            preset["models"] = []
            for row in rows:
                mid = row.get("id") if isinstance(row, dict) else None
                if not isinstance(mid, str):
                    continue
                meta = metadata.get(mid, {})
                if is_free_zen_model(mid):
                    preset["models"].append(_model({**meta, "id": mid}))
            continue
        go = identity in {"opencode-go-openai", "opencode-go-anthropic"}
        upstream = registry.get("opencode-go" if go else identity, {})
        if not isinstance(upstream, dict):
            continue
        if not upstream and not (go and go_ids):
            continue
        # Metadata can enrich supported presets but must not alter endpoint/auth.
        bundled = {m["id"]: m for m in preset["models"]}
        models = []
        upstream_models = upstream.get("models")
        if not isinstance(upstream_models, dict):
            upstream_models = {}
        for mid, value in upstream_models.items():
            if not isinstance(value, dict) or not isinstance(mid, str):
                continue
            if go:
                if go_ids is not None and mid not in go_ids:
                    continue
                if go_ids is None and value.get("status") == "deprecated":
                    continue
                provider = value.get("provider")
                if not isinstance(provider, dict):
                    provider = {}
                api = str(provider.get("api", ""))
                is_anthropic = "anthropic" in api or (not api and mid.startswith("claude-"))
                if (preset["protocol"] == "anthropic") != is_anthropic:
                    continue
                if mid.startswith("gemini-"):
                    continue
            elif value.get("status") == "deprecated":
                continue
            converted = _model({**value, "id": mid})
            if (
                go
                and mid not in bundled
                and isinstance(value.get("provider"), dict)
                and value["provider"].get("npm") == "@ai-sdk/openai"
            ):
                converted["use_responses_api"] = True
            # Protocol overrides/reasoning adapters remain owned by Octop.
            models.append({**deepcopy(bundled.get(mid, {})), **converted})
        if go and preset["protocol"] == "openai" and go_ids:
            known = {model["id"] for model in models}
            upstream_ids = set(upstream_models)
            models.extend(
                {"id": mid, "name": mid, "enabled": True}
                for mid in sorted(go_ids - known - upstream_ids)
                if not mid.startswith(("claude-", "gemini-"))
            )
        if models:
            preset["models"] = models
    return presets


def free_hub_entries() -> list[dict[str, Any]]:
    """Public directory only: never transmit keys to its operator."""
    result = []
    for row in snapshot().get("free-models-hub", {}).get("data", {}).get("items", []):
        if not isinstance(row, dict):
            continue

        def https(value: Any) -> str:
            if not isinstance(value, str) or len(value) > 2048:
                return ""
            try:
                url = urlsplit(value)
                return (
                    value
                    if url.scheme == "https"
                    and url.hostname
                    and not url.username
                    and not url.password
                    else ""
                )
            except ValueError:
                return ""

        base, signup = https(row.get("api_base_url")), https(row.get("key_apply_url"))
        models = row.get("model_name", [])
        models = [models] if isinstance(models, str) else models
        if not base or not isinstance(models, list):
            continue
        ids = list(
            dict.fromkeys(
                m.strip()
                for m in models
                if isinstance(m, str) and m.strip() and not m.endswith("/")
            )
        )[:100]
        if ids:
            result.append(
                {
                    "id": str(row.get("id", "")),
                    "name": str(row.get("title", ""))[:100],
                    "base_url": base,
                    "signup_url": signup,
                    "models": ids,
                }
            )
    return result
