"""Management-plane egress allowlist skeleton (0028 DEC-I04 / S0).

S0 ships the policy object and a pure check hook. Full enforcement against
management HTTP clients is **S1** (AC-I04). Expert tool egress continues to use
device grants / command guards (unchanged).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class EgressPolicy:
    """Allowlisted hostnames (exact or suffix) for management outbound HTTPS."""

    allow_hosts: tuple[str, ...] = ()
    allow_suffixes: tuple[str, ...] = ()
    deny_private: bool = True
    enabled: bool = False
    notes: str = ""

    def normalized_hosts(self) -> frozenset[str]:
        return frozenset(h.strip().lower().rstrip(".") for h in self.allow_hosts if h.strip())

    def normalized_suffixes(self) -> tuple[str, ...]:
        out: list[str] = []
        for suffix in self.allow_suffixes:
            text = suffix.strip().lower().rstrip(".")
            if text and text not in out:
                out.append(text)
        return tuple(out)


def default_management_egress_policy() -> EgressPolicy:
    """Conservative skeleton: disabled until operators configure hosts."""
    return EgressPolicy(
        allow_hosts=(),
        allow_suffixes=(),
        deny_private=True,
        enabled=False,
        notes="S0 skeleton — enable via OCTOP_EGRESS_ALLOWLIST_JSON or config file",
    )


def load_egress_policy_from_env(*, env: dict[str, str] | None = None) -> EgressPolicy:
    """Load policy from ``OCTOP_EGRESS_ALLOWLIST_JSON`` or path env."""
    source = env if env is not None else os.environ
    raw_json = str(source.get("OCTOP_EGRESS_ALLOWLIST_JSON", "")).strip()
    path_raw = str(source.get("OCTOP_EGRESS_ALLOWLIST_PATH", "")).strip()
    data: dict[str, Any] | None = None
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return default_management_egress_policy()
        if isinstance(parsed, dict):
            data = parsed
    elif path_raw:
        path = Path(path_raw).expanduser()
        if path.is_file():
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return default_management_egress_policy()
            if isinstance(parsed, dict):
                data = parsed
    if data is None:
        return default_management_egress_policy()
    hosts = data.get("allow_hosts") or data.get("hosts") or []
    suffixes = data.get("allow_suffixes") or data.get("suffixes") or []
    if not isinstance(hosts, list):
        hosts = []
    if not isinstance(suffixes, list):
        suffixes = []
    enabled = bool(data.get("enabled", True))
    deny_private = bool(data.get("deny_private", True))
    return EgressPolicy(
        allow_hosts=tuple(str(h) for h in hosts),
        allow_suffixes=tuple(str(s) for s in suffixes),
        deny_private=deny_private,
        enabled=enabled,
        notes=str(data.get("notes") or "loaded from env"),
    )


def is_management_egress_allowed(
    url: str,
    *,
    policy: EgressPolicy | None = None,
) -> bool:
    """Return whether *url* may be fetched by management-plane code.

    When the policy is disabled (S0 default), returns True so existing flows
    keep working. When enabled, hostname must match allow_hosts or suffixes.
    """
    pol = policy if policy is not None else default_management_egress_policy()
    if not pol.enabled:
        return True
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    if host in pol.normalized_hosts():
        return True
    for suffix in pol.normalized_suffixes():
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


@dataclass
class EgressHook:
    """Placeholder for S1 wiring into management HTTP clients."""

    policy: EgressPolicy = field(default_factory=default_management_egress_policy)

    def check(self, url: str) -> bool:
        return is_management_egress_allowed(url, policy=self.policy)
