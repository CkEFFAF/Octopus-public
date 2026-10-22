"""Shared connector credential validation and merging; never exposes vault contents."""

from __future__ import annotations

from typing import Any

from octop.infra.connectors.builder import normalize_weiyun_mcp_token, validate_create_credentials
from octop.infra.connectors.catalog import get_catalog_entry
from octop.infra.connectors.oauth import exchange_pasted_auth_code


def redact_credential_values(value: Any, credentials: dict[str, Any], *, kind: str) -> Any:
    """Keep secrets out of operation results, including vendor error strings."""
    keys = {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "cookie",
        "internal_token",
        "app_secret",
        "bot_secret",
        "client_secret",
        "secret_key",
        "oauth_client_secret",
        "code",
        "device_code",
    }
    entry = get_catalog_entry(kind)
    if entry:
        keys.update(field.key for field in entry.credential_fields if field.secret)
    secrets = [str(credentials[key]) for key in keys if credentials.get(key)]

    def scrub(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: "[redacted]" if key in keys else scrub(val) for key, val in item.items()}
        if isinstance(item, list):
            return [scrub(val) for val in item]
        if isinstance(item, str):
            for secret in sorted(secrets, key=len, reverse=True):
                item = item.replace(secret, "[redacted]")
        return item

    return scrub(value)


async def prepare_credentials(
    kind: str,
    credentials: dict[str, Any],
    settings_repo: Any,
) -> dict[str, Any]:
    entry = get_catalog_entry(kind)
    if entry is None:
        raise ValueError(f"unknown connector kind: {kind}")
    cred_payload = dict(credentials)
    if entry.auth_kind == "auth_code" and cred_payload.get("code"):
        code = str(cred_payload.pop("code")).strip()
        extra = {
            k: cred_payload.pop(k) for k in ("bkn", "knowledge_base_id") if cred_payload.get(k)
        }
        exchanged = await exchange_pasted_auth_code(
            kind=kind,
            code=code,
            settings_repo=settings_repo,
            extra=extra or None,
        )
        cred_payload.update(exchanged)
    elif entry.kind == "tencent-weiyun" and entry.auth_kind == "personal_token":
        raw = str(cred_payload.get("token") or cred_payload.get("access_token") or "").strip()
        token = normalize_weiyun_mcp_token(raw)
        if not token:
            raise ValueError("token is required")
        cred_payload = {"token": token}
    return validate_create_credentials(kind, cred_payload)


def merge_credentials(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    kind: str | None = None,
) -> dict[str, Any]:
    # QCC: switching auth mode must replace the other mode's secrets, not layer them.
    if kind == "qcc":
        new_api_key = str(new.get("api_key") or "").strip()
        new_access = str(new.get("access_token") or new.get("token") or "").strip()
        oauth_in_new = bool(new.get("oauth_client_id") or new.get("refresh_token") or new_access)
        if new_api_key and not oauth_in_new:
            out: dict[str, Any] = {"api_key": new_api_key}
            if old.get("internal_token"):
                out["internal_token"] = old["internal_token"]
            return out
        if oauth_in_new:
            merged_oauth = dict(old)
            for key, value in new.items():
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                merged_oauth[key] = value
            merged_oauth.pop("api_key", None)
            return merged_oauth
    merged = dict(old)
    for key, value in new.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged
