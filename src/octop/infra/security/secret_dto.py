"""Public DTO helpers: strip secrets from API responses (0038 F04/F05)."""

from __future__ import annotations

import json
from typing import Any

# Keys stripped from nested JSON / extra maps (case-insensitive match on key).
_SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "secretkey",
        "secret_id",
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "private_key",
        "client_secret",
        "authorization",
    }
)


def _is_secret_key(name: str) -> bool:
    cleaned = name.strip().lower().replace("-", "_")
    if cleaned in _SECRET_KEY_NAMES:
        return True
    if cleaned.endswith("_api_key") or cleaned.endswith("_secret"):
        return True
    return False


def redact_mapping(raw: Any) -> tuple[dict[str, Any], bool]:
    """Return a shallow-redacted copy of a mapping and whether secrets were present."""
    if not isinstance(raw, dict):
        return {}, False
    out: dict[str, Any] = {}
    had_secret = False
    for key, value in raw.items():
        key_s = str(key)
        if _is_secret_key(key_s):
            had_secret = True
            continue
        if isinstance(value, dict):
            nested, nested_secret = redact_mapping(value)
            out[key_s] = nested
            had_secret = had_secret or nested_secret
        else:
            out[key_s] = value
    return out, had_secret


def redact_config_json(raw: str | None) -> tuple[str | None, bool]:
    """Redact secret keys inside a JSON object string; non-objects pass through empty."""
    if raw is None:
        return None, False
    text = str(raw).strip()
    if not text:
        return None, False
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        # Opaque non-JSON config: never echo to clients.
        return None, True
    if not isinstance(parsed, dict):
        return None, True
    redacted, had = redact_mapping(parsed)
    if not redacted and not had:
        return text, False
    return json.dumps(redacted, ensure_ascii=False, separators=(",", ":")), had


def has_nonempty_secret(value: str | None) -> bool:
    return bool(value and str(value).strip())


def merge_mapping_preserving_secrets(
    incoming: Any,
    existing: Any,
) -> dict[str, Any]:
    """Merge *incoming* over *existing*, keeping secret keys omitted from incoming.

    Used when clients round-trip a redacted public DTO on PATCH: missing secret
    keys mean "keep", explicit null/empty string means "clear", and a new value
    replaces. Nested dicts merge the same way.
    """
    base = dict(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return base
    out = dict(base)
    for key, value in incoming.items():
        key_s = str(key)
        if isinstance(value, dict):
            out[key_s] = merge_mapping_preserving_secrets(value, base.get(key_s))
            continue
        if _is_secret_key(key_s):
            if value is None or (isinstance(value, str) and not value.strip()):
                # Explicit clear.
                out.pop(key_s, None)
            else:
                out[key_s] = value
            continue
        out[key_s] = value
    return out


def merge_config_json_preserving_secrets(
    incoming: str | None,
    existing: str | None,
) -> str | None:
    """Merge redacted/partial config_json over the stored JSON without dropping secrets.

    ``None`` or blank *incoming* clears to empty. Non-JSON opaque blobs replace
    only when *incoming* is non-empty (clients cannot round-trip opaques).
    """
    if incoming is None or not str(incoming).strip():
        return ""
    try:
        new_obj = json.loads(incoming)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(incoming)
    old_obj: Any = {}
    if existing and str(existing).strip():
        try:
            parsed = json.loads(existing)
            if isinstance(parsed, dict):
                old_obj = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            old_obj = {}
    if not isinstance(new_obj, dict):
        return str(incoming)
    merged = merge_mapping_preserving_secrets(new_obj, old_obj)
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
