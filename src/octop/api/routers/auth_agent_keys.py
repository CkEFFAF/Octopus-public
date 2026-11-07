"""Agent access keys (oaa_) — create / list / revoke / optional exchange."""

from __future__ import annotations

import time
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from octop.api.common.agent import assert_agent_access_row, user_owns_agent
from octop.api.common.client_ip import resolve_client_ip
from octop.api.deps import (
    current_user,
    get_server,
    require_human_session,
    sign_token,
)
from octop.infra.auth.agent_access_keys import AGENT_SCOPES, AgentAccessKeyService
from octop.infra.errors import ErrorCode, OctopError

router = APIRouter()

AgentScope = Literal[
    "experts.read",
    "tasks.create",
    "tasks.read",
    "tasks.input",
    "tasks.cancel",
    "resources.read",
]


class CreateAgentKeyBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    days: int = Field(default=30, ge=1, le=365)
    scopes: list[AgentScope] = Field(min_length=1)
    expert_ids: list[str] = Field(min_length=1)
    allow_existing_threads: bool = False


class AgentAccessKeyInfo(BaseModel):
    key_id: str
    owner_user_id: int
    name: str
    prefix: str
    scopes: list[str]
    expert_ids: list[str]
    allow_existing_threads: bool
    expires_at: float
    revoked_at: float | None = None
    last_used_at: float | None = None
    created_at: float


class AcpLaunchTemplate(BaseModel):
    command: str
    args: list[str]
    env_names: list[str]
    protocol: dict[str, Any]
    notes: str


class AgentAccessKeyCreated(BaseModel):
    key: AgentAccessKeyInfo
    secret: str = Field(repr=False)
    acp_launch: AcpLaunchTemplate


class AgentAccessKeyList(BaseModel):
    keys: list[AgentAccessKeyInfo]


class ExchangeBody(BaseModel):
    secret: str = Field(min_length=1, max_length=200, repr=False)


class ExpertCandidate(BaseModel):
    expert_id: str
    name: str
    kind: str


def _svc(server: Any) -> AgentAccessKeyService:
    return cast(AgentAccessKeyService, server.app_runtime.devices.agent_access_keys)


def _acp_launch(*, server_url: str, expert_id: str) -> dict[str, Any]:
    return {
        "command": "octop",
        "args": [
            "acp-remote",
            "--server",
            server_url,
            "--expert",
            expert_id,
            "--token-file",
            "%OCTOP_ACP_TOKEN_FILE%",
        ],
        "env_names": ["OCTOP_ACP_SERVER", "OCTOP_ACP_EXPERT", "OCTOP_ACP_TOKEN_FILE"],
        "protocol": {
            "package": "agent-client-protocol",
            "package_version": "0.11.0",
            "schema_ref": "refs/tags/schema-v1.16.0",
            "protocol_version": 1,
        },
        "notes": (
            "Put the secret in a private file referenced by OCTOP_ACP_TOKEN_FILE. "
            "Never paste the secret into IDE args."
        ),
    }


def _public_base(request: Request, server: Any) -> str:
    configured = getattr(getattr(server, "services", None), "config", None)
    base = getattr(configured, "public_base_url", None) if configured else None
    if isinstance(base, str) and base.strip():
        return base.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.post(
    "/agent-access-keys",
    status_code=201,
    summary="Create a restricted agent access key; secret returned once",
    response_model=AgentAccessKeyCreated,
)
async def create_agent_access_key(
    body: CreateAgentKeyBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    require_human_session(request)
    # Validate experts are accessible to this user (agent ids).
    for expert_id in body.expert_ids:
        row = server.services.agent_repo.get(expert_id.strip())
        if row is None:
            raise OctopError(ErrorCode.DEVICE_INVALID, f"unknown expert {expert_id}", status=422)
        try:
            assert_agent_access_row(row, user)
        except OctopError as exc:
            raise OctopError(
                ErrorCode.DEVICE_INVALID, f"expert not allowed: {expert_id}", status=422
            ) from exc
    created = _svc(server).create(
        int(user.id),
        name=body.name,
        days=body.days,
        scopes=list(body.scopes),
        expert_ids=list(body.expert_ids),
        allow_existing_threads=body.allow_existing_threads,
    )
    expert = body.expert_ids[0]
    return {
        "key": created["key"],
        "secret": created["secret"],
        "acp_launch": _acp_launch(server_url=_public_base(request, server), expert_id=expert),
    }


@router.get(
    "/agent-access-keys",
    summary="List your agent access keys (no secrets)",
    response_model=AgentAccessKeyList,
)
async def list_agent_access_keys(
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    require_human_session(request)
    return {"keys": _svc(server).list_keys(int(user.id))}


@router.post(
    "/agent-access-keys/{key_id}/revoke",
    status_code=204,
    summary="Revoke an agent access key",
)
async def revoke_agent_access_key(
    key_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Response:
    require_human_session(request)
    _svc(server).revoke(int(user.id), key_id)
    return Response(status_code=204)


@router.get(
    "/agent-access-keys/experts",
    summary="Experts eligible for agent-access-key allowlists",
    response_model=list[ExpertCandidate],
)
async def list_agent_key_experts(
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    require_human_session(request)
    out: list[dict[str, Any]] = []
    for row in server.services.agent_repo.list_by_user(int(user.id), include_disabled=False):
        out.append({"expert_id": row.agent_id, "name": row.name, "kind": "agent"})
    for row in server.services.agent_repo.list_shared(exclude_user_id=int(user.id)):
        if user_owns_agent(row, user):
            continue
        try:
            assert_agent_access_row(row, user)
        except OctopError:
            continue
        out.append({"expert_id": row.agent_id, "name": row.name, "kind": "shared_agent"})
    return out


@router.post(
    "/agent-access-keys/exchange",
    summary="Exchange oaa_ secret for a short-lived machine JWT",
)
async def exchange_agent_access_key(
    body: ExchangeBody,
    request: Request,
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    principal = _svc(server).authenticate(body.secret, resolve_client_ip(request))
    user = server.user_manager.get_by_id(principal.owner_user_id)
    if user is None:
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")
    ttl = min(900, max(60, int(server.services.config.access_token_ttl_seconds)))
    # Cap by key expiry
    row = server.services.repos.agent_access_key_repo.get(principal.credential_id)
    if row is not None:
        ttl = min(ttl, max(1, int(float(row["expires_at"]) - time.time())))
    token = sign_token(
        server.services.secret_repo.get("jwt"),
        sub=user.id,
        uname=user.username,
        role=user.role,
        ttl_seconds=ttl,
        auth_key_id=principal.credential_id,
        actor_kind="machine",
        scopes=sorted(principal.scopes),
        experts=sorted(principal.expert_allowlist),
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "actor_kind": "machine",
        "scopes": sorted(principal.scopes),
        "experts": sorted(principal.expert_allowlist),
    }


# Silence unused import lint for AGENT_SCOPES documentation surface
_ = AGENT_SCOPES
