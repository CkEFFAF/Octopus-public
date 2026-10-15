"""Device zero-downtime update policy API (0017). Separate from Hub PyPI /update."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_admin
from octop.infra.devices.update_policy import (
    VALID_UPDATE_STATUSES,
    build_offer,
    default_policy,
    load_policy_from_settings,
    parse_policy,
    save_policy_to_settings,
)
from octop.infra.devices.updater import resolve_software_version
from octop.infra.errors import ErrorCode, OctopError

router = APIRouter()


class DeviceUpdatePolicyBody(BaseModel):
    target_version: str = ""
    channel: str = "stable"
    window_local: dict[str, int] = Field(default_factory=lambda: {"start_hour": 0, "end_hour": 8})
    batch_percent: int = 100
    force: bool = False
    deferrable: bool = True
    skip_when_busy: bool = True
    manifest: dict[str, Any] | None = None
    published_at: str | None = None
    notes: str | None = None


class DeviceUpdateReportBody(BaseModel):
    status: str
    software_version: str | None = None
    error: str | None = None
    stage_version: str | None = None
    busy: bool | None = None
    busy_reasons: list[str] | None = None


def _settings_repo(server: Any) -> Any:
    return server.services.settings_repo


def _device_repo(server: Any) -> Any:
    return server.services.repos.device_repo


@router.get("/device-update/policy", summary="Get device update policy")
async def get_policy(
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    policy = load_policy_from_settings(_settings_repo(server).get)
    payload = policy.to_dict()
    if not policy.target_version:
        return {**default_policy(), **payload}
    return payload


@router.put("/device-update/policy", summary="Set device update policy")
async def put_policy(
    body: DeviceUpdatePolicyBody,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    try:
        policy = parse_policy(body.model_dump())
    except ValueError as exc:
        raise OctopError(ErrorCode.DEVICE_INVALID, str(exc)) from exc
    save_policy_to_settings(_settings_repo(server).set, policy)
    return policy.to_dict()


@router.get("/device-update/devices", summary="List device update statuses")
async def list_device_updates(
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    policy = load_policy_from_settings(_settings_repo(server).get)
    repo = _device_repo(server)
    rows: list[Any] = repo.list_all()
    out: list[dict[str, Any]] = []
    for row in rows:
        offer = build_offer(policy, device_id=row.device_id, platform=row.platform)
        meta = row.runtime_metadata or {}
        out.append(
            {
                "device_id": row.device_id,
                "software_version": row.software_version,
                "update_status": row.update_status or "idle",
                "last_error": meta.get("update_error"),
                "eligible": offer is not None,
                "platform": row.platform,
                "name": row.name,
            }
        )
    return out


@router.get("/devices/me/update", summary="Device: fetch personal update offer")
async def device_me_update(
    device_id: str,
    token: str,
    deferred: bool = False,
    tz: str | None = None,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    devices = getattr(getattr(server, "app_runtime", None), "devices", None)
    if devices is None:
        raise OctopError(ErrorCode.NOT_FOUND, "device service unavailable")
    row = devices.authenticate(device_id, token)
    policy = load_policy_from_settings(_settings_repo(server).get)
    offer = build_offer(
        policy,
        device_id=row.device_id,
        platform=row.platform,
        deferred=deferred,
        tz_name=tz,
    )
    return {
        "offer": offer,
        "software_version": row.software_version or resolve_software_version(),
    }


@router.post("/devices/me/update/report", summary="Device: report update progress")
async def device_me_update_report(
    body: DeviceUpdateReportBody,
    device_id: str,
    token: str,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    devices = getattr(getattr(server, "app_runtime", None), "devices", None)
    if devices is None:
        raise OctopError(ErrorCode.NOT_FOUND, "device service unavailable")
    row = devices.authenticate(device_id, token)
    status = body.status.strip().lower()
    if status not in VALID_UPDATE_STATUSES:
        raise OctopError(ErrorCode.DEVICE_INVALID, f"invalid status {status!r}")
    updated = _device_repo(server).set_update_report(
        row.device_id,
        status=status,
        software_version=body.software_version,
        error=body.error,
        stage_version=body.stage_version,
    )
    return {
        "device_id": updated.device_id,
        "software_version": updated.software_version,
        "update_status": updated.update_status,
    }


__all__ = ["router"]
