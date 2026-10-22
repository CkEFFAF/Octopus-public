"""Refresh persisted provider model catalogs (remote + bundled preset)."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from octop.infra.agents.providers.model_flags import is_local_runtime_provider
from octop.infra.agents.providers.presets import load_provider_presets
from octop.infra.agents.providers.probe import (
    fetch_openai_compatible_models,
    provider_headers,
)
from octop.infra.agents.providers.store import clear_stale_pins_for_provider

# Protocols that can list models via OpenAI-compatible GET /models (S0).
_REMOTE_LIST_KINDS = frozenset({"openai"})


def remote_list_supported(kind: str) -> bool:
    return (kind or "").strip().lower() in _REMOTE_LIST_KINDS


def match_provider_preset(row: Any) -> dict[str, Any] | None:
    """Match a saved provider row to a bundled preset by name or id."""
    name = str(getattr(row, "name", "") or "").strip()
    if not name:
        return None
    for preset in load_provider_presets():
        if name in {str(preset.get("name") or ""), str(preset.get("id") or "")}:
            return preset
    return None


def _as_model_id(item: dict[str, Any] | Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or "").strip()
    return str(getattr(item, "id", "") or "").strip()


def _enrich_from_preset(model: dict[str, Any], preset: dict[str, Any] | None) -> dict[str, Any]:
    """Fill empty metadata fields from preset without clobbering user choices."""
    if not preset:
        return model
    out = dict(model)
    if out.get("use_responses_api") is None and preset.get("use_responses_api") is not None:
        out["use_responses_api"] = preset.get("use_responses_api")
    mid = str(out.get("id") or "")
    if out.get("name") in (None, "", mid) and preset.get("name"):
        out["name"] = preset["name"]
    if out.get("input") is None and preset.get("input") is not None:
        out["input"] = deepcopy(preset.get("input"))
    if out.get("reasoning") is None and preset.get("reasoning") is not None:
        out["reasoning"] = preset.get("reasoning")
    if out.get("reasoning_config") is None and preset.get("reasoning_config") is not None:
        out["reasoning_config"] = deepcopy(preset.get("reasoning_config"))
    if out.get("context_window") is None:
        cw = preset.get("context_window")
        if cw is None:
            cw = preset.get("max_input_tokens")
        if cw is not None:
            out["context_window"] = cw
    if out.get("max_tokens") is None and preset.get("max_tokens") is not None:
        out["max_tokens"] = preset.get("max_tokens")
    if out.get("max_output_tokens") is None and preset.get("max_output_tokens") is not None:
        out["max_output_tokens"] = preset.get("max_output_tokens")
    return out


def _new_from_catalog(
    *,
    model_id: str,
    name: str | None,
    preset: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": model_id,
        "name": (preset or {}).get("name") or name or model_id,
        "enabled": False,
        "input": deepcopy((preset or {}).get("input")) or ["text"],
        "thinking": None,
        "source": source,
    }
    if preset and preset.get("use_responses_api") is not None:
        base["use_responses_api"] = preset.get("use_responses_api")
    if preset and preset.get("reasoning") is not None:
        base["reasoning"] = preset.get("reasoning")
    if preset and preset.get("reasoning_config") is not None:
        base["reasoning_config"] = deepcopy(preset.get("reasoning_config"))
    if preset:
        cw = preset.get("context_window")
        if cw is None:
            cw = preset.get("max_input_tokens")
        if cw is not None:
            base["context_window"] = cw
        if preset.get("max_tokens") is not None:
            base["max_tokens"] = preset.get("max_tokens")
        if preset.get("max_output_tokens") is not None:
            base["max_output_tokens"] = preset.get("max_output_tokens")
        if preset.get("embedding") is not None:
            base["embedding"] = preset.get("embedding")
        if preset.get("task") is not None:
            base["task"] = preset.get("task")
    return base


def merge_models_with_source(
    current: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
    presets: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge current DB models with remote + preset catalogs.

    Never deletes current entries. Tags ``source`` as user|remote|preset.
    Returns ``(merged_models, stats)`` where stats has added/enriched/kept_user.
    """
    presets = presets or []
    catalog = {str(p.get("id") or ""): p for p in presets if p.get("id")}
    fetched_map: dict[str, dict[str, Any]] = {}
    for item in fetched:
        mid = _as_model_id(item)
        if not mid:
            continue
        if isinstance(item, dict):
            fetched_map[mid] = item
        else:
            fetched_map[mid] = {"id": mid, "name": mid}

    fetched_ids = set(fetched_map)
    preset_ids = set(catalog)

    result: list[dict[str, Any]] = []
    existing: set[str] = set()
    enriched_count = 0
    kept_user: list[dict[str, str]] = []
    added: list[dict[str, str]] = []

    for raw in current:
        model = dict(raw)
        mid = str(model.get("id") or "").strip()
        if not mid:
            continue
        before = json.dumps(model, sort_keys=True, default=str)
        model = _enrich_from_preset(model, catalog.get(mid))
        if json.dumps(model, sort_keys=True, default=str) != before and mid in catalog:
            enriched_count += 1
        if mid not in fetched_ids and mid not in preset_ids:
            model["source"] = "user"
            kept_user.append({"id": mid})
        elif mid in fetched_ids:
            model["source"] = "remote"
        else:
            model["source"] = "preset"
        result.append(model)
        existing.add(mid)

    for mid, fmodel in fetched_map.items():
        if mid in existing:
            continue
        entry = _new_from_catalog(
            model_id=mid,
            name=str(fmodel.get("name") or mid),
            preset=catalog.get(mid),
            source="remote",
        )
        result.append(entry)
        existing.add(mid)
        added.append({"id": mid, "source": "remote"})

    for mid, preset in catalog.items():
        if mid in existing:
            continue
        entry = _new_from_catalog(
            model_id=mid,
            name=str(preset.get("name") or mid),
            preset=preset,
            source="preset",
        )
        result.append(entry)
        existing.add(mid)
        added.append({"id": mid, "source": "preset"})

    stats = {
        "added": added,
        "enriched": enriched_count,
        "kept_user": kept_user,
    }
    return result, stats


async def refresh_provider_models(
    *,
    row: Any,
    server: Any,
    locale: str | None = None,
    prefer: str = "auto",
) -> dict[str, Any]:
    """Refresh one saved provider: optional remote list + preset merge + persist.

    On success writes ``models_json``. On failure returns ok=False and does not write.
    """
    prefer = (prefer or "auto").strip().lower()
    if prefer not in {"auto", "remote", "preset"}:
        prefer = "auto"

    kind = str(getattr(row, "kind", "") or "").strip().lower()
    api_key = (getattr(row, "api_key", None) or "").strip()
    remote_supported = remote_list_supported(kind)
    is_local = is_local_runtime_provider(
        getattr(row, "name", ""),
        provider_api_key=getattr(row, "api_key", None),
        provider_base_url=getattr(row, "base_url", None),
    )

    preset = match_provider_preset(row)
    preset_models: list[dict[str, Any]] = list((preset or {}).get("models") or [])

    if is_local:
        return {
            "ok": False,
            "provider_id": row.id,
            "source_used": None,
            "remote_supported": False,
            "added": [],
            "enriched": 0,
            "kept_user": [],
            "models": None,
            "error": (
                "local runtime providers manage models on-device; refresh-models is disabled"
            ),
        }

    remote_ok = False
    remote_models: list[dict[str, Any]] = []
    remote_err: str | None = None

    want_remote = prefer in {"auto", "remote"} and remote_supported and bool(api_key)
    if prefer == "remote" and not remote_supported:
        return {
            "ok": False,
            "provider_id": row.id,
            "source_used": None,
            "remote_supported": False,
            "added": [],
            "enriched": 0,
            "kept_user": [],
            "models": None,
            "error": ("remote model listing is only supported for openai-compatible providers"),
        }
    if prefer == "remote" and not api_key:
        return {
            "ok": False,
            "provider_id": row.id,
            "source_used": None,
            "remote_supported": remote_supported,
            "added": [],
            "enriched": 0,
            "kept_user": [],
            "models": None,
            "error": "api_key is required for remote model listing",
        }

    if want_remote:
        result = await fetch_openai_compatible_models(
            base_url=(getattr(row, "base_url", None) or "").strip() or None,
            api_key=api_key,
            extra_headers=provider_headers(row) or None,
            locale=locale,
            provider_name=str(getattr(row, "name", "") or "") or None,
        )
        if result.get("ok"):
            remote_ok = True
            remote_models = list(result.get("models") or [])
        else:
            remote_err = str(result.get("error") or "remote model listing failed")
            if prefer == "remote":
                return {
                    "ok": False,
                    "provider_id": row.id,
                    "source_used": None,
                    "remote_supported": True,
                    "added": [],
                    "enriched": 0,
                    "kept_user": [],
                    "models": None,
                    "error": remote_err,
                }

    if prefer == "preset":
        remote_ok = False
        remote_models = []

    if not remote_ok and not preset_models:
        err = remote_err
        if not err:
            if not remote_supported:
                err = "no bundled preset matched this provider; remote listing unavailable"
            elif not api_key:
                err = "api_key is required for remote model listing"
            else:
                err = "no model catalog available"
        return {
            "ok": False,
            "provider_id": row.id,
            "source_used": None,
            "remote_supported": remote_supported,
            "added": [],
            "enriched": 0,
            "kept_user": [],
            "models": None,
            "error": err,
        }

    current: list[dict[str, Any]] = []
    if hasattr(row, "get_models"):
        current = list(row.get_models() or [])
    elif getattr(row, "models_json", None):
        try:
            parsed = json.loads(row.models_json)
            if isinstance(parsed, list):
                current = [dict(m) for m in parsed if isinstance(m, dict)]
        except (TypeError, ValueError, json.JSONDecodeError):
            current = []

    merged, stats = merge_models_with_source(
        current,
        remote_models if remote_ok else [],
        preset_models,
    )

    if remote_ok and preset_models:
        source_used = "remote+preset"
    elif remote_ok:
        source_used = "remote"
    else:
        source_used = "preset"

    models_json = json.dumps(merged, ensure_ascii=False)
    server.services.provider_repo.update(
        row.user_id,
        row.id,
        models_json=models_json,
    )
    clear_stale_pins_for_provider(
        agent_repo=server.services.agent_repo,
        settings_repo=server.services.settings_repo,
        user_id=row.user_id,
        provider_name=row.name,
        models=merged,
    )
    if server.app_runtime:
        await server.app_runtime.agent_registry.on_provider_changed(
            user_id=row.user_id, provider_name=row.name
        )

    return {
        "ok": True,
        "provider_id": row.id,
        "source_used": source_used,
        "remote_supported": remote_supported,
        "added": stats["added"],
        "enriched": stats["enriched"],
        "kept_user": stats["kept_user"],
        "models": merged,
        "error": None,
    }
