"""Dashboard plugins: shared definitions, private installs, official quota lookup."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from octop.infra.connectors.crypto import decrypt_credentials, encrypt_credentials
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.plugins.models import (
    CatalogPlugin,
    CostMeterConfigPatch,
    CostMeterState,
    GoQuota,
    PeakState,
    PluginInstallation,
    PluginInstallationPatch,
    QuotaWindow,
)

GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
_BEIJING = ZoneInfo("Asia/Shanghai")
_MAX_RESPONSE = 262_144
_CATALOG = (
    {
        "id": "cost-meter",
        "name": "DeepSeek & Go",
        "version": "0.1.0",
        "description": "DeepSeek peak/off-peak clock and OpenCode Go quota monitor",
        "category": "usage",
        "source_url": "https://github.com/Han-1413141/dsh-cost-meter",
    },
)

# 2026 State Council holiday calendar. Weekends remain off-peak even on
# compensatory working days, matching DeepSeek's Beijing calendar rule.
_HOLIDAY_RANGES = (
    ("2026-01-01", "2026-01-03"),
    ("2026-02-15", "2026-02-23"),
    ("2026-04-04", "2026-04-06"),
    ("2026-05-01", "2026-05-05"),
    ("2026-06-19", "2026-06-21"),
    ("2026-09-25", "2026-09-27"),
    ("2026-10-01", "2026-10-07"),
)


def _phase(at: datetime) -> tuple[bool, str]:
    local = at.astimezone(_BEIJING)
    day = local.date().isoformat()
    if any(start <= day <= end for start, end in _HOLIDAY_RANGES):
        return False, "holiday"
    if local.weekday() >= 5:
        return False, "weekend"
    hour = local.hour + local.minute / 60
    return 9 <= hour < 12 or 14 <= hour < 18, "weekday"


def peak_state(at: datetime) -> PeakState:
    """Find the next real phase change, including weekends and public holidays."""
    in_peak, reason = _phase(at)
    today = at.astimezone(_BEIJING).date()
    for offset in range(40):
        for hour in (9, 12, 14, 18):
            candidate = datetime.combine(today + timedelta(days=offset), time(hour), _BEIJING)
            if candidate > at and _phase(candidate)[0] != in_peak:
                return PeakState(
                    in_peak=in_peak,
                    reason=reason,  # type: ignore[arg-type]
                    next_change_at=candidate.astimezone(UTC),
                    calendar_supported=today.year == 2026,
                )
    raise RuntimeError("peak calendar has no transition")


def _window(raw: object) -> QuotaWindow | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("percent")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        percent = float(value)
    except ValueError:
        return None
    if not math.isfinite(percent) or percent < 0:
        return None
    reset = None
    if isinstance(raw.get("resetsAt"), str):
        try:
            parsed = datetime.fromisoformat(raw["resetsAt"].replace("Z", "+00:00"))
            reset = parsed if parsed.tzinfo is not None else None
        except ValueError:
            pass
    return QuotaWindow(percent=percent, resets_at=reset)


class PluginMarketplace:
    def __init__(self, services: SharedServices):
        self.services = services

    @staticmethod
    def _key(user_id: int, suffix: str) -> str:
        return f"dashboard_plugins.user.{user_id}.{suffix}"

    def _record(
        self, user_id: int, plugin_id: str = "cost-meter"
    ) -> tuple[str | None, dict[str, Any]]:
        raw = self.services.settings_repo.get(self._key(user_id, f"{plugin_id}.state"))
        return raw, json.loads(raw) if raw else {}

    def _replace(
        self, user_id: int, plugin_id: str, expected: str | None, record: dict[str, Any]
    ) -> bool:
        return self.services.settings_repo.compare_and_set(
            self._key(user_id, f"{plugin_id}.state"), expected, json.dumps(record)
        )

    @staticmethod
    def _conflict() -> OctopError:
        return OctopError(
            ErrorCode.WORKFLOW_CONFLICT, "plugin settings changed; reload before saving"
        )

    @staticmethod
    def _assert_plugin(plugin_id: str) -> None:
        if not any(item["id"] == plugin_id for item in _CATALOG):
            raise OctopError(ErrorCode.NOT_FOUND, "dashboard plugin not found")

    def installation(self, user_id: int, plugin_id: str = "cost-meter") -> PluginInstallation:
        self._assert_plugin(plugin_id)
        _, record = self._record(user_id, plugin_id)
        return PluginInstallation.model_validate(record.get("installation", {}))

    def catalog(self, user_id: int) -> list[CatalogPlugin]:
        return [
            CatalogPlugin.model_validate(
                {**item, **self.installation(user_id, item["id"]).model_dump()}
            )
            for item in _CATALOG
        ]

    def install(
        self, user_id: int, plugin_id: str, patch: PluginInstallationPatch
    ) -> PluginInstallation:
        self._assert_plugin(plugin_id)
        raw, record = self._record(user_id, plugin_id)
        value = PluginInstallation(installed=True, **patch.model_dump())
        if not record:
            record["generation"] = uuid4().hex
        record["installation"] = value.model_dump()
        if not self._replace(user_id, plugin_id, raw, record):
            raise self._conflict()
        return value

    def uninstall(self, user_id: int, plugin_id: str) -> None:
        self._assert_plugin(plugin_id)
        self.services.settings_repo.delete(self._key(user_id, f"{plugin_id}.state"))

    def state(self, user_id: int) -> CostMeterState:
        now = datetime.now(UTC)
        _, record = self._record(user_id)
        config = record.get("config", {})
        installed = PluginInstallation.model_validate(record.get("installation", {}))
        key_configured = bool(config.get("credential"))
        quota = GoQuota.model_validate(record.get("quota", {}))
        if not key_configured:
            quota = GoQuota()
        elif quota.status == "unconfigured":
            quota.status = "idle"
        return CostMeterState(
            installation=installed,
            server_time=now,
            peak=peak_state(now),
            go=quota,
            key_configured=key_configured,
            subscription_expires_at=config.get("expires_at"),
            subscription_source="manual" if config.get("expires_at") else None,
        )

    def configure(self, user_id: int, patch: CostMeterConfigPatch) -> CostMeterState:
        raw, record = self._record(user_id)
        if not record.get("installation", {}).get("installed"):
            raise OctopError(ErrorCode.NOT_FOUND, "install the dashboard plugin first")
        config = record.get("config", {})
        key_changed = False
        if patch.clear_go_api_key:
            config.pop("credential", None)
            key_changed = True
        elif patch.go_api_key is not None:
            key = patch.go_api_key.get_secret_value().strip()
            if key.lower().startswith("bearer "):
                key = key[7:].strip()
            if key:
                if any(not 33 <= ord(char) <= 126 for char in key):
                    raise OctopError(
                        ErrorCode.CONNECTOR_INVALID_CREDENTIALS, "invalid API key characters"
                    )
                encrypted = encrypt_credentials(self.services.secret_repo, {"api_key": key})
                config["credential"] = encrypted.decode("ascii")
                key_changed = True
        if "subscription_expires_at" in patch.model_fields_set:
            config["expires_at"] = (
                patch.subscription_expires_at.isoformat() if patch.subscription_expires_at else None
            )
        config["revision"] = uuid4().hex
        record["config"] = config
        if key_changed:
            record.pop("quota", None)
        if not self._replace(user_id, "cost-meter", raw, record):
            raise self._conflict()
        return self.state(user_id)

    async def refresh(self, user_id: int) -> CostMeterState:
        raw, record = self._record(user_id)
        installed = PluginInstallation.model_validate(record.get("installation", {}))
        if not installed.installed or not installed.enabled:
            return self.state(user_id)
        config = record.get("config", {})
        credential = config.get("credential")
        if not credential:
            return self.state(user_id)
        # All clients for this account share a short cooldown. Other accounts
        # have their own cache and credentials. No service-wide environment keys.
        now = datetime.now(UTC)
        previous = GoQuota.model_validate(record.get("quota", {}))
        if previous.attempted_at and (now - previous.attempted_at).total_seconds() < 15:
            return self.state(user_id)
        quota = previous.model_copy(update={"attempted_at": now})
        record["quota"] = quota.model_dump(mode="json")
        pending = json.dumps(record)
        if not self.services.settings_repo.compare_and_set(
            self._key(user_id, "cost-meter.state"), raw, pending
        ):
            return self.state(user_id)
        key = decrypt_credentials(self.services.secret_repo, credential.encode("ascii"))["api_key"]
        error = None
        try:
            async with (
                httpx.AsyncClient(timeout=15, follow_redirects=False) as client,
                client.stream(
                    "GET",
                    GO_USAGE_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Accept": "application/json",
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/140.0.0.0 Safari/537.36"
                        ),
                    },
                ) as response,
            ):
                if response.status_code == 401:
                    error = "auth_failed"
                elif response.status_code == 403:
                    error = "access_denied"
                elif response.status_code == 429:
                    error = "rate_limited"
                elif response.status_code != 200:
                    error = "upstream_error"
                else:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE:
                            raise ValueError("quota response too large")
                    data = json.loads(body)
                    usage = data.get("usage") if isinstance(data, dict) else None
                    if not isinstance(usage, dict):
                        raise ValueError("missing usage")
                    windows = {
                        name: _window(usage.get(name)) for name in ("rolling", "weekly", "monthly")
                    }
                    if not any(windows.values()):
                        raise ValueError("no quota windows")
                    quota = GoQuota(
                        status="ok",
                        fetched_at=now,
                        attempted_at=now,
                        rolling=windows["rolling"],
                        weekly=windows["weekly"],
                        monthly=windows["monthly"],
                    )
        except httpx.HTTPError:
            error = "network_error"
        except (ValueError, TypeError):
            error = "invalid_response"
        if error:
            # Keep the last successful data visibly stale. Do not relay the
            # upstream body, which may echo a credential in an error message.
            quota = quota.model_copy(update={"status": "error", "error_code": error})
        record["quota"] = quota.model_dump(mode="json")
        self._replace(user_id, "cost-meter", pending, record)
        return self.state(user_id)
