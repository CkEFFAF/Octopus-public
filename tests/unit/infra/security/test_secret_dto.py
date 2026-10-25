"""0038 F04/F05 secret DTO helpers."""

from __future__ import annotations

import json

from octop.infra.security.secret_dto import (
    has_nonempty_secret,
    merge_config_json_preserving_secrets,
    merge_mapping_preserving_secrets,
    redact_config_json,
    redact_mapping,
)


def test_redact_mapping_strips_nested_secrets() -> None:
    public, had = redact_mapping(
        {"region": "ap", "api_key": "SECRET", "nested": {"token": "T", "ok": 1}}
    )
    assert had is True
    assert public == {"region": "ap", "nested": {"ok": 1}}
    assert "SECRET" not in json.dumps(public)


def test_redact_config_json_and_merge_preserves_secrets() -> None:
    stored = json.dumps({"api_key": "KEEP_ME", "sandbox_scope": "agent"})
    public, had = redact_config_json(stored)
    assert had is True
    assert "KEEP_ME" not in (public or "")
    # Client round-trips redacted public config plus a non-secret edit.
    incoming = json.dumps({"sandbox_scope": "user", "username": "alice"})
    merged = merge_config_json_preserving_secrets(incoming, stored)
    assert merged is not None
    obj = json.loads(merged)
    assert obj["api_key"] == "KEEP_ME"
    assert obj["sandbox_scope"] == "user"
    assert obj["username"] == "alice"


def test_merge_explicit_empty_secret_clears() -> None:
    merged = merge_mapping_preserving_secrets(
        {"api_key": "", "region": "x"},
        {"api_key": "OLD", "region": "y"},
    )
    assert "api_key" not in merged
    assert merged["region"] == "x"


def test_has_nonempty_secret() -> None:
    assert has_nonempty_secret("abc") is True
    assert has_nonempty_secret("  ") is False
    assert has_nonempty_secret(None) is False
