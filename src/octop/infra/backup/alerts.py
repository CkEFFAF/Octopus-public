"""Minimal ops alert channel for backup / disk events (0026 DEC-B09)."""

from __future__ import annotations

import json
import logging
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

AlertKind = Literal[
    "backup_failed",
    "offsite_failed",
    "disk_low",
    "db_growth",
    "unexpected_restart",
]


@dataclass(frozen=True)
class AlertSettings:
    webhook_url: str = ""
    disk_free_percent_min: float = 15.0


@dataclass(frozen=True)
class AlertDelivery:
    kind: AlertKind
    delivered: bool
    detail: str = ""


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_alert(
    settings: AlertSettings,
    kind: AlertKind,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> AlertDelivery:
    """POST a JSON payload to the configured webhook.

    When ``webhook_url`` is empty, logs at ERROR and returns ``delivered=False``
    (still counts as an attempt for operators reading logs — DEC-B09: failures
    must not be ``logger.exception`` only when a channel is configured; when
    unset we at least ERROR-log).
    """
    payload = {
        "source": "octop",
        "kind": kind,
        "message": message,
        "detail": detail or {},
        "created_at": _utc_now(),
    }
    url = (settings.webhook_url or "").strip()
    if not url:
        logger.error(
            "octop alert [%s]: %s (no webhook configured) detail=%s", kind, message, detail
        )
        return AlertDelivery(kind=kind, delivered=False, detail="webhook_url empty")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "octop-backup-alert/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            status = getattr(response, "status", 200)
            if int(status) >= 400:
                logger.error("alert webhook HTTP %s for %s", status, kind)
                return AlertDelivery(kind=kind, delivered=False, detail=f"http {status}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("alert webhook failed for %s: %s", kind, exc)
        return AlertDelivery(kind=kind, delivered=False, detail=str(exc)[:300])

    logger.warning("octop alert delivered [%s]: %s", kind, message)
    return AlertDelivery(kind=kind, delivered=True, detail="ok")


def disk_free_percent(path: Path) -> float:
    """Return free space percent for the filesystem containing *path*."""
    usage = shutil.disk_usage(Path(path))
    if usage.total <= 0:
        return 100.0
    return (usage.free / usage.total) * 100.0


def check_disk_and_alert(settings: AlertSettings, *, home: Path) -> AlertDelivery | None:
    """AC-B06 skeleton: alert when free disk percent is below threshold."""
    free_pct = disk_free_percent(home)
    threshold = float(settings.disk_free_percent_min)
    if free_pct >= threshold:
        return None
    return emit_alert(
        settings,
        "disk_low",
        f"disk free {free_pct:.1f}% < {threshold:.1f}% under {home}",
        detail={"free_percent": round(free_pct, 2), "threshold": threshold, "home": str(home)},
    )
