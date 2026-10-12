"""Thin authenticated adapters for account devices and their private socket."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from octop.api.common.client_ip import resolve_client_ip
from octop.api.deps import _decode, current_user, extract_raw_token, get_server, resolve_user_from_token
from octop.infra.devices.protocol import MAX_FRAME
from octop.infra.devices.service import DeviceConnection, DeviceService
from octop.infra.errors import ErrorCode, OctopError

router = APIRouter()


def device_service(server: Any = Depends(get_server)) -> DeviceService:
    return cast(DeviceService, server.app_runtime.devices)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RootBody(StrictBody):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=4096)
    read: bool = True
    write: bool = False


class EnrollBody(StrictBody):
    pairing_code: str | None = Field(default=None, min_length=1, max_length=120)
    access_key: str | None = Field(default=None, min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    platform: str
    capabilities: list[str] = Field(max_length=6)
    permissions: list[str] = Field(max_length=6)
    roots: list[RootBody] = Field(default_factory=list, max_length=20)


class UpdateBody(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    permissions: list[str] | None = Field(default=None, max_length=6)


class CallBody(StrictBody):
    action: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = Field(default=None, max_length=120)


class TransferBody(StrictBody):
    source_device_id: str
    source_root_id: str
    source_path: str = Field(min_length=1, max_length=4096)
    target_device_id: str
    target_root_id: str
    target_path: str = Field(min_length=1, max_length=4096)


@router.get("/devices")
async def list_devices(
    user: Any = Depends(current_user), service: DeviceService = Depends(device_service)
) -> dict[str, Any]:
    return {"devices": service.list_devices(int(user.id))}


@router.post("/devices/pairing")
async def pairing(
    request: Request,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    raw = extract_raw_token(
        authorization=request.headers.get("authorization"),
        access_token=request.query_params.get("access_token"),
    )
    if raw and _decode(request.app.state.octop_server, raw).get("auth_key_id") is not None:
        from octop.infra.errors import ErrorCode

        raise OctopError(
            ErrorCode.FORBIDDEN, "sign in with password or SSO to create pairing codes"
        )
    return service.pairing(int(user.id))


@router.post("/devices/enroll", status_code=201)
async def enroll(
    body: EnrollBody, request: Request, service: DeviceService = Depends(device_service)
) -> dict[str, Any]:
    """Enroll with pairing_code, access_key, or a Bearer account session JWT.

    The path stays JWT-exempt so pairing/key clients need no prior login; when a
    Bearer token is the sole credential, owner_user_id is taken from the token
    (never from the body). Key-session JWTs (auth_key_id) are rejected — use the
    access key or a password/SSO session instead.
    """
    payload = body.model_dump()
    roots = [r.model_dump() for r in body.roots]
    raw = extract_raw_token(
        authorization=request.headers.get("authorization"),
        access_token=request.query_params.get("access_token"),
    )
    has_pair = bool(payload.get("pairing_code"))
    has_key = bool(payload.get("access_key"))
    owner_user_id: int | None = None
    if raw:
        if has_pair or has_key:
            raise OctopError(
                ErrorCode.AUTH_FAILED, "provide one enrollment credential"
            )
        server = request.app.state.octop_server
        claims = _decode(server, raw)
        if claims.get("auth_key_id") is not None:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "access key sessions cannot enroll devices; use the access key or a password login",
            )
        user = resolve_user_from_token(server, raw)
        owner_user_id = int(user.id)
    return service.enroll(
        pairing_code=payload.get("pairing_code"),
        access_key=payload.get("access_key"),
        owner_user_id=owner_user_id,
        name=payload["name"],
        platform=payload["platform"],
        capabilities=payload["capabilities"],
        permissions=payload["permissions"],
        roots=roots,
        client_ip=resolve_client_ip(request),
    )


@router.get("/devices/operations")
async def operations(
    device_id: str | None = None,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    owner = int(user.id)
    if device_id:
        service.owned(owner, device_id, active=False)
    return {
        "operations": [
            r.public()
            for r in service.repos.device_repo.list_operations(owner, device_id=device_id)
        ]
    }


@router.get("/devices/operations/{operation_id}")
async def operation(
    operation_id: str,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return service.operation(int(user.id), operation_id).public()


@router.post("/devices/operations/{operation_id}/confirm")
async def confirm(
    operation_id: str,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return service.confirm(int(user.id), operation_id)


@router.post("/devices/operations/{operation_id}/cancel")
async def cancel(
    operation_id: str,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return await service.cancel(int(user.id), operation_id)


@router.post("/devices/transfers", status_code=202)
async def transfer(
    body: TransferBody,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return service.transfer(int(user.id), body.model_dump())


@router.patch("/devices/{device_id}")
async def update(
    device_id: str,
    body: UpdateBody,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return await service.update(int(user.id), device_id, **body.model_dump(exclude_unset=True))


@router.post("/devices/{device_id}/revoke")
async def revoke(
    device_id: str,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return await service.revoke(int(user.id), device_id)


@router.post("/devices/{device_id}/operations", status_code=202)
async def submit(
    device_id: str,
    body: CallBody,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return service.submit(int(user.id), device_id, body.action, body.params, agent_id=body.agent_id)


@router.post("/devices/{device_id}/call")
async def call(
    device_id: str,
    body: CallBody,
    user: Any = Depends(current_user),
    service: DeviceService = Depends(device_service),
) -> dict[str, Any]:
    return await service.call(
        int(user.id), device_id, body.action, body.params, agent_id=body.agent_id
    )


@router.websocket("/devices/connect/ws")
async def connect(websocket: WebSocket) -> None:
    await websocket.accept()
    service = cast(DeviceService, websocket.app.state.octop_server.app_runtime.devices)
    connection: DeviceConnection | None = None
    lock = asyncio.Lock()

    async def send(frame: dict[str, Any]) -> None:
        async with lock:
            await websocket.send_json(frame)

    async def close() -> None:
        await websocket.close(code=4003)

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), 10)
        if len(raw) > 4096:
            raise ValueError("invalid hello")
        hello = json.loads(raw)
        if (
            not isinstance(hello, dict)
            or hello.get("type") != "hello"
            or hello.get("protocol") != 1
        ):
            raise ValueError("invalid hello")
        device_id = hello.get("device_id")
        token = hello.get("token")
        if not isinstance(device_id, str) or not isinstance(token, str):
            raise ValueError("invalid credentials")
        connection = await service.connect(device_id, token, send, close)
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), 60)
            if len(raw.encode("utf-8")) > MAX_FRAME:
                raise ValueError("frame too large")
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                raise ValueError("invalid frame")
            await service.receive(connection, frame)
    except (OctopError, ValueError, TypeError, TimeoutError, WebSocketDisconnect):
        if websocket.client_state.name != "DISCONNECTED":
            with contextlib.suppress(RuntimeError):
                await close()
    finally:
        if connection is not None:
            service.disconnect(connection)
