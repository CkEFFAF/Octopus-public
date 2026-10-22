"""Best-effort upstream model metadata (models.dev) for provider refresh.

Catalog failures must never block persisting remotely listed model ids (0036.1).
"""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MODELS_DEV_URL = "https://models.dev/api.json"
_MODELS_DEV_TIMEOUT_S = 10.0
_MODELS_DEV_TTL_S = 6 * 60 * 60
_USER_AGENT = "OctopusProviderRefresh/0036.1"

# Octopus preset id / display name / alias → models.dev provider key.
_PROVIDER_KEY_BY_IDENTITY: dict[str, str] = {
    "opencode-go-openai": "opencode-go",
    "opencode-go-compatible": "opencode-go",
    "OpenCode Go (Compatible)": "opencode-go",
}

_cache_payload: dict[str, Any] | None = None
_cache_fetched_at: float = 0.0


def reset_upstream_catalog_cache() -> None:
    """Clear the in-process models.dev cache (tests)."""
    global _cache_payload, _cache_fetched_at
    _cache_payload = None
    _cache_fetched_at = 0.0


def resolve_models_dev_provider_key(
    *,
    preset_id: str | None = None,
    provider_name: str | None = None,
) -> str | None:
    """Map an Octopus provider identity to a models.dev provider key."""
    for candidate in (preset_id, provider_name):
        key = str(candidate or "").strip()
        if not key:
            continue
        mapped = _PROVIDER_KEY_BY_IDENTITY.get(key)
        if mapped:
            return mapped
        # Same-name fallback: openai-compatible providers whose key exists upstream.
        if key in {"openai", "openrouter", "groq", "deepseek", "opencode", "opencode-go"}:
            return key
    return None


async def fetch_models_dev_api(*, force: bool = False) -> dict[str, Any] | None:
    """GET models.dev api.json with a short in-process TTL cache.

    Returns the parsed top-level object, or None on any failure.
    """
    global _cache_payload, _cache_fetched_at
    now = time.monotonic()
    if (
        not force
        and _cache_payload is not None
        and (now - _cache_fetched_at) < _MODELS_DEV_TTL_S
    ):
        return _cache_payload
    try:
        async with httpx.AsyncClient(timeout=_MODELS_DEV_TIMEOUT_S) as client:
            response = await client.get(
                _MODELS_DEV_URL,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )
        if response.status_code >= 400:
            logger.info(
                "models.dev fetch failed: HTTP %s",
                response.status_code,
            )
            return None
        payload = response.json()
        if not isinstance(payload, dict):
            logger.info("models.dev fetch failed: payload is not an object")
            return None
        _cache_payload = payload
        _cache_fetched_at = now
        return payload
    except Exception as exc:
        logger.info("models.dev fetch failed: %r (%s)", exc, type(exc).__name__)
        return None


def _upstream_model_entry(
    catalog: dict[str, Any], *, provider_key: str, model_id: str
) -> dict[str, Any] | None:
    provider = catalog.get(provider_key)
    if not isinstance(provider, dict):
        return None
    models = provider.get("models")
    if not isinstance(models, dict):
        return None
    entry = models.get(model_id)
    return entry if isinstance(entry, dict) else None


def _fill_empty_from_upstream(model: dict[str, Any], upstream: dict[str, Any]) -> bool:
    """Fill blank Octopus model fields from a models.dev entry. Returns True if changed."""
    out = model
    changed = False
    mid = str(out.get("id") or "")

    name = upstream.get("name")
    if isinstance(name, str) and name.strip() and out.get("name") in (None, "", mid):
        out["name"] = name.strip()
        changed = True

    limit = upstream.get("limit") if isinstance(upstream.get("limit"), dict) else {}
    context = limit.get("context")
    if out.get("context_window") is None and isinstance(context, (int, float)):
        out["context_window"] = int(context)
        changed = True
    output = limit.get("output")
    if out.get("max_output_tokens") is None and isinstance(output, (int, float)):
        out["max_output_tokens"] = int(output)
        changed = True

    modalities = upstream.get("modalities") if isinstance(upstream.get("modalities"), dict) else {}
    inputs = modalities.get("input")
    if out.get("input") is None and isinstance(inputs, list) and inputs:
        out["input"] = deepcopy(inputs)
        changed = True

    if out.get("reasoning") is None and isinstance(upstream.get("reasoning"), bool):
        out["reasoning"] = upstream["reasoning"]
        changed = True

    # OQ-0036.1-2: cost optional; write only when the field is already absent/empty.
    cost = upstream.get("cost")
    if out.get("cost") is None and isinstance(cost, dict) and cost:
        out["cost"] = deepcopy(cost)
        changed = True

    return changed


async def enrich_models_from_upstream(
    models: list[dict[str, Any]],
    *,
    provider_key: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """Best-effort models.dev enrich. Never raises; returns (models, enriched_count)."""
    if not provider_key or not models:
        return models, 0
    try:
        catalog = await fetch_models_dev_api()
        if not catalog:
            return models, 0
        enriched = 0
        result: list[dict[str, Any]] = []
        for raw in models:
            model = dict(raw)
            mid = str(model.get("id") or "").strip()
            if not mid:
                result.append(model)
                continue
            upstream = _upstream_model_entry(catalog, provider_key=provider_key, model_id=mid)
            if upstream and _fill_empty_from_upstream(model, upstream):
                enriched += 1
            result.append(model)
        return result, enriched
    except Exception as exc:
        logger.info(
            "models.dev enrich failed for provider_key=%s: %r (%s)",
            provider_key,
            exc,
            type(exc).__name__,
        )
        return models, 0
