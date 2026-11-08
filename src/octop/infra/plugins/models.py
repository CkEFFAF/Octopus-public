"""Public dashboard plugin contracts. Credentials never enter response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


class PluginInstallation(BaseModel):
    installed: bool = False
    enabled: bool = False
    show_in_chat: bool = True


class PluginInstallationPatch(BaseModel):
    enabled: bool = True
    show_in_chat: bool = True


class CatalogPlugin(PluginInstallation):
    id: str
    name: str
    version: str
    description: str
    category: str
    source_url: str


class QuotaWindow(BaseModel):
    percent: float = Field(ge=0)
    resets_at: datetime | None = None


class GoQuota(BaseModel):
    status: Literal["unconfigured", "idle", "ok", "error"] = "unconfigured"
    error_code: str | None = None
    fetched_at: datetime | None = None
    attempted_at: datetime | None = None
    rolling: QuotaWindow | None = None
    weekly: QuotaWindow | None = None
    monthly: QuotaWindow | None = None


class PeakState(BaseModel):
    in_peak: bool
    reason: Literal["weekday", "weekend", "holiday"]
    next_change_at: datetime
    calendar_supported: bool
    timezone: str = "Asia/Shanghai"


class CostMeterState(BaseModel):
    installation: PluginInstallation
    server_time: datetime
    peak: PeakState
    go: GoQuota
    key_configured: bool = False
    subscription_expires_at: datetime | None = None
    subscription_source: Literal["manual"] | None = None


class CostMeterConfigPatch(BaseModel):
    go_api_key: SecretStr | None = Field(default=None, max_length=4096)
    clear_go_api_key: bool = False
    subscription_expires_at: datetime | None = None

    @field_validator("subscription_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("a timezone offset is required")
        return value
