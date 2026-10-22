"""Read-only effective model catalogs for recognized built-in OpenCode Go rows."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from octop.infra.agents.providers.presets import load_provider_presets

_GO_IDENTITIES = {
    "opencode-go-openai": (
        "opencode-go-openai",
        "OpenCode Go (Compatible)",
        "opencode-go-compatible",
    ),
    "opencode-go-anthropic": ("opencode-go-anthropic", "OpenCode Go (Anthropic)"),
}
_GO_ENDPOINTS = {
    "openai": frozenset(
        {
            "https://opencode.ai/zen/go/v1",
            "https://opencode.ai/inference/go/v1",
            "https://opencode.ai/inference/go/openai/v1",
        }
    ),
    "anthropic": frozenset(
        {
            "https://opencode.ai/zen/go",
            "https://opencode.ai/inference/go",
            "https://opencode.ai/inference/go/anthropic",
        }
    ),
}


def is_opencode_go_openai(*, base_url: str | None, provider_name: str | None) -> bool:
    """True when name+endpoint match the bundled OpenCode Go OpenAI-compatible identity.

    Used for list-URL rewrite only — never as a model-id whitelist.
    """
    name = str(provider_name or "").strip()
    if name not in _GO_IDENTITIES["opencode-go-openai"]:
        return False
    root = str(base_url or "").strip().rstrip("/")
    return root in _GO_ENDPOINTS["openai"]


def effective_provider_models(provider: Any) -> list[dict[str, Any]]:
    """Fill missing Go metadata and append selectable models without writing rows.

    Exact preset identity, protocol and a known public Go base must all match.
    Persisted entries keep their order and every explicit value, including false
    and zero. Custom providers and Zen receive only their persisted catalog.
    """
    current: list[dict[str, Any]] = (
        deepcopy(provider.get_models()) if hasattr(provider, "get_models") else []
    )
    kind = str(getattr(provider, "kind", "") or "")
    base_url = str(getattr(provider, "base_url", "") or "").rstrip("/")
    if base_url not in _GO_ENDPOINTS.get(kind, frozenset()):
        return current
    name = str(getattr(provider, "name", "") or "")
    preset_id = next((key for key, names in _GO_IDENTITIES.items() if name in names), None)
    if preset_id is None:
        return current
    preset = next(
        (p for p in load_provider_presets() if p["id"] == preset_id and p["protocol"] == kind), None
    )
    if preset is None:
        return current

    catalog = {model["id"]: model for model in preset["models"]}
    for model in current:
        metadata = catalog.get(model.get("id"))
        if metadata is None:
            continue
        # Legacy aliases already determine the runtime budget. Do not populate
        # their missing counterpart from a larger catalog value.
        context_override = any(
            model.get(key) is not None for key in ("context_window", "max_input_tokens")
        )
        output_override = any(
            model.get(key) is not None for key in ("max_output_tokens", "max_tokens")
        )
        reasoning_override = (
            model.get("reasoning") is False or model.get("reasoning_config") is not None
        )
        for key, value in metadata.items():
            if value is None or model.get(key) is not None:
                continue
            if key in {"context_window", "max_input_tokens"} and context_override:
                continue
            if key in {"max_output_tokens", "max_tokens"} and output_override:
                continue
            if key in {"reasoning", "reasoning_config"} and reasoning_override:
                continue
            model[key] = deepcopy(value)
    existing = {model.get("id") for model in current}
    for model_id, metadata in catalog.items():
        if model_id not in existing:
            current.append({**deepcopy(metadata), "enabled": True})
            existing.add(model_id)
    return current
