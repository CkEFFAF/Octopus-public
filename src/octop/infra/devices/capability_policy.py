"""Device capability policy packs (0025): MCP / Skill scopes on a device row."""

from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = 1
_LIST_KEYS = (
    "mcp_servers",
    "skill_package_ids",
    "deny_mcp_servers",
    "deny_skill_package_ids",
)


def empty_policy() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mcp_servers": [],
        "skill_package_ids": [],
        "deny_mcp_servers": [],
        "deny_skill_package_ids": [],
    }


def _unique_names(values: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(values, list):
        return out
    for item in values:
        text = str(item).strip() if item is not None else ""
        if text and text not in out:
            out.append(text)
    return out


def parse_capability_policy(raw: Any) -> dict[str, Any]:
    """Normalize stored JSON / dict into a schema_version=1 policy."""
    policy = empty_policy()
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return policy
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return policy
    if data is None:
        return policy
    if not isinstance(data, dict):
        return policy
    version = data.get("schema_version", SCHEMA_VERSION)
    try:
        policy["schema_version"] = int(version) if version is not None else SCHEMA_VERSION
    except (TypeError, ValueError):
        policy["schema_version"] = SCHEMA_VERSION
    for key in _LIST_KEYS:
        policy[key] = _unique_names(data.get(key))
    return policy


def dump_capability_policy(policy: dict[str, Any] | None) -> str | None:
    """Serialize a policy for DB storage; None / empty → NULL (no device contribution)."""
    if policy is None:
        return None
    normalized = parse_capability_policy(policy)
    if not any(normalized[key] for key in _LIST_KEYS):
        return None
    return json.dumps(normalized, ensure_ascii=False)


def validate_capability_policy_shape(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Reject unknown keys; return normalized policy."""
    if policy is None:
        return empty_policy()
    if not isinstance(policy, dict):
        raise ValueError("capability_policy must be an object")
    allowed = {"schema_version", *_LIST_KEYS}
    unknown = sorted(set(policy) - allowed)
    if unknown:
        raise ValueError(f"capability_policy unknown keys: {unknown}")
    return parse_capability_policy(policy)


def policy_missing_mcp(policy: dict[str, Any], active_names: set[str] | list[str]) -> list[str]:
    """Names listed on the device pack that are not available to the owner."""
    allowed = set(active_names)
    return [name for name in policy.get("mcp_servers", []) if name not in allowed]


def seed_mcp_into_policy(
    existing: dict[str, Any] | None,
    *,
    mcp_servers: list[str],
) -> dict[str, Any]:
    """Idempotently union mcp_servers into a policy (ops seed helper)."""
    policy = parse_capability_policy(existing)
    for name in _unique_names(mcp_servers):
        if name not in policy["mcp_servers"]:
            policy["mcp_servers"].append(name)
    return policy
