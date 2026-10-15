"""Device zero-downtime update policy (0017) — Hub-side validation & eligibility."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

POLICY_SETTINGS_KEY = "device_update.policy"

VALID_CHANNELS = frozenset({"stable", "beta"})
VALID_UPDATE_STATUSES = frozenset(
    {"idle", "downloading", "staged", "healthy", "failed", "rolled_back", "ok"}
)


@dataclass(frozen=True)
class WindowLocal:
    start_hour: int
    end_hour: int

    def contains_local_hour(self, hour: int) -> bool:
        if not (0 <= self.start_hour < self.end_hour <= 24):
            return False
        return self.start_hour <= hour < self.end_hour


@dataclass(frozen=True)
class AssetSpec:
    platform: str
    kind: str
    url: str
    sha256: str
    size: int | None = None


@dataclass(frozen=True)
class DeviceUpdatePolicy:
    target_version: str
    channel: str = "stable"
    window_local: WindowLocal = WindowLocal(0, 8)
    batch_percent: int = 100
    force: bool = False
    deferrable: bool = True
    skip_when_busy: bool = True
    manifest: dict[str, Any] | None = None
    published_at: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target_version": self.target_version,
            "channel": self.channel,
            "window_local": {
                "start_hour": self.window_local.start_hour,
                "end_hour": self.window_local.end_hour,
            },
            "batch_percent": self.batch_percent,
            "force": self.force,
            "deferrable": self.deferrable,
            "skip_when_busy": self.skip_when_busy,
        }
        if self.manifest is not None:
            out["manifest"] = self.manifest
        if self.published_at is not None:
            out["published_at"] = self.published_at
        if self.notes is not None:
            out["notes"] = self.notes
        return out


def default_policy() -> dict[str, Any]:
    return {
        "target_version": "",
        "channel": "stable",
        "window_local": {"start_hour": 0, "end_hour": 8},
        "batch_percent": 100,
        "force": False,
        "deferrable": True,
        "skip_when_busy": True,
        "manifest": None,
        "published_at": None,
        "notes": None,
    }


def parse_policy(raw: dict[str, Any] | None) -> DeviceUpdatePolicy:
    """Validate and normalize a policy body. Raises ValueError on bad input."""
    data = dict(default_policy())
    if raw:
        data.update(raw)
    target = str(data.get("target_version") or "").strip()
    channel = str(data.get("channel") or "stable").strip().lower()
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel must be one of {sorted(VALID_CHANNELS)}")
    window = data.get("window_local") or {"start_hour": 0, "end_hour": 8}
    if not isinstance(window, dict):
        raise ValueError("window_local must be an object")
    try:
        start = int(window.get("start_hour", 0))
        end = int(window.get("end_hour", 8))
    except (TypeError, ValueError) as exc:
        raise ValueError("window_local hours must be integers") from exc
    # MVP: forbid overnight windows (start >= end).
    if not (0 <= start < end <= 24):
        raise ValueError("window_local requires 0 <= start_hour < end_hour <= 24 (no overnight)")
    try:
        batch = int(data.get("batch_percent", 100))
    except (TypeError, ValueError) as exc:
        raise ValueError("batch_percent must be an integer") from exc
    if not (0 <= batch <= 100):
        raise ValueError("batch_percent must be 0..100")
    manifest = data.get("manifest")
    if manifest is not None and not isinstance(manifest, dict):
        raise ValueError("manifest must be an object or null")
    if target and manifest is not None:
        assets = manifest.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ValueError("manifest.assets must be a non-empty list when target_version is set")
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("manifest.assets entries must be objects")
            for key in ("platform", "kind", "url", "sha256"):
                if not str(asset.get(key) or "").strip():
                    raise ValueError(f"manifest.assets[].{key} is required")
            if channel == "stable":
                kind = str(asset.get("kind") or "").lower()
                url = str(asset.get("url") or "").lower()
                # Soft guard: reject assets explicitly tagged beta in channel stable.
                if "beta" in url or kind == "beta":
                    raise ValueError("stable channel cannot include beta assets")
    return DeviceUpdatePolicy(
        target_version=target,
        channel=channel,
        window_local=WindowLocal(start, end),
        batch_percent=batch,
        force=bool(data.get("force", False)),
        deferrable=bool(data.get("deferrable", True)),
        skip_when_busy=bool(data.get("skip_when_busy", True)),
        manifest=manifest if isinstance(manifest, dict) else None,
        published_at=(str(data["published_at"]) if data.get("published_at") else None),
        notes=(str(data["notes"]) if data.get("notes") else None),
    )


def load_policy_from_settings(get_value: Callable[[str], str | None]) -> DeviceUpdatePolicy:
    raw = get_value(POLICY_SETTINGS_KEY)
    if not raw:
        return parse_policy(None)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return parse_policy(None)
    if not isinstance(parsed, dict):
        return parse_policy(None)
    try:
        return parse_policy(parsed)
    except ValueError:
        return parse_policy(None)


def save_policy_to_settings(
    set_value: Callable[[str, str], None], policy: DeviceUpdatePolicy
) -> None:
    set_value(POLICY_SETTINGS_KEY, json.dumps(policy.to_dict(), ensure_ascii=False))


def batch_eligible(device_id: str, batch_percent: int) -> bool:
    if batch_percent <= 0:
        return False
    if batch_percent >= 100:
        return True
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < batch_percent


def in_local_window(
    window: WindowLocal,
    *,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> bool:
    """Evaluate cutover window against device-local time (MVP: no overnight)."""
    if now is None:
        if tz_name:
            try:
                now = datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = datetime.now().astimezone()
        else:
            now = datetime.now().astimezone()
    elif now.tzinfo is None and tz_name:
        with contextlib.suppress(Exception):
            now = now.replace(tzinfo=ZoneInfo(tz_name))
    return window.contains_local_hour(now.hour)


def pick_asset(manifest: dict[str, Any] | None, platform: str) -> AssetSpec | None:
    if not manifest:
        return None
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        return None
    platform_l = platform.lower()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("platform") or "").lower() != platform_l:
            continue
        return AssetSpec(
            platform=str(asset["platform"]),
            kind=str(asset["kind"]),
            url=str(asset["url"]),
            sha256=str(asset["sha256"]).lower(),
            size=int(asset["size"]) if asset.get("size") is not None else None,
        )
    return None


def build_offer(
    policy: DeviceUpdatePolicy,
    *,
    device_id: str,
    platform: str,
    deferred: bool = False,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return a device-facing offer dict, or None when not eligible."""
    if not policy.target_version:
        return None
    if not batch_eligible(device_id, policy.batch_percent):
        return None
    if deferred and policy.deferrable and not policy.force:
        return None
    asset = pick_asset(policy.manifest, platform)
    if asset is None:
        return None
    # Download may be allowed outside window; cutover is gated separately.
    return {
        "type": "device_update.offer",
        "target_version": policy.target_version,
        "channel": policy.channel,
        "window_local": {
            "start_hour": policy.window_local.start_hour,
            "end_hour": policy.window_local.end_hour,
        },
        "force": policy.force,
        "deferrable": policy.deferrable,
        "skip_when_busy": policy.skip_when_busy,
        "in_window": in_local_window(policy.window_local, now=now, tz_name=tz_name),
        "asset": {
            "url": asset.url,
            "sha256": asset.sha256,
            "platform": asset.platform,
            "kind": asset.kind,
            **({"size": asset.size} if asset.size is not None else {}),
        },
    }


def may_cutover(
    policy: DeviceUpdatePolicy,
    *,
    busy: bool,
    deferred: bool = False,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> bool:
    if deferred and policy.deferrable and not policy.force:
        return False
    if not in_local_window(policy.window_local, now=now, tz_name=tz_name) and not policy.force:
        return False
    return not (policy.skip_when_busy and busy and not policy.force)


__all__ = [
    "POLICY_SETTINGS_KEY",
    "VALID_CHANNELS",
    "VALID_UPDATE_STATUSES",
    "AssetSpec",
    "DeviceUpdatePolicy",
    "WindowLocal",
    "batch_eligible",
    "build_offer",
    "default_policy",
    "in_local_window",
    "load_policy_from_settings",
    "may_cutover",
    "parse_policy",
    "pick_asset",
    "save_policy_to_settings",
]
