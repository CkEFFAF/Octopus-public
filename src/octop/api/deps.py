"""FastAPI Depends, JWT helpers, and auth routing."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from fastapi import Depends, Header, Query, Request

from octop.infra.auth.agent_access_keys import MachinePrincipal
from octop.infra.auth.tokens import InvalidToken as InvalidToken
from octop.infra.auth.tokens import TokenExpired as TokenExpired
from octop.infra.auth.tokens import decode_token as decode_token
from octop.infra.auth.tokens import sign_token as sign_token
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.permissions import PERMISSIONS, user_has_permission

if TYPE_CHECKING:
    from octop.infra.server import OctopServer
    from octop.infra.users.identity import User
else:
    from octop.infra.users.identity import User


# Sliding renew: when remaining life is below this fraction of configured TTL,
# middleware issues a fresh access token via ACCESS_TOKEN_RESPONSE_HEADER.
ACCESS_TOKEN_RESPONSE_HEADER = "X-Octop-Access-Token"
_SLIDING_RENEW_REMAINING_FRACTION = 1 / 3


# Paths that bypass JWT middleware (setup wizard, health, login).
_JWT_EXEMPT_PREFIXES = (
    "/api/setup/",
    "/api/health/",
    "/api/i18n/",
    "/api/connectors/oauth/callback",
    "/api/internal/mcp/",
)
_JWT_EXEMPT_EXACT = (
    "/api/devices/enroll",
    "/api/health",
    "/api/auth/login",
    "/api/auth/key-login",
    "/api/auth/agent-access-keys/exchange",
    "/api/auth/captcha",
    "/api/auth/oidc/status",
    "/api/auth/oidc/start",
    "/api/auth/oidc/callback",
    "/api/auth/oidc/exchange",
    "/api/auth/oauth/status",
    "/api/auth/oauth/start",
    "/api/auth/oauth/callback",
    "/api/auth/oauth/exchange",
    "/api/auth/ldap/status",
    "/api/auth/invite/validate",
    "/api/auth/invite/redeem",
    "/api/docs",
    "/api/openapi.json",
)


def is_jwt_exempt_path(path: str) -> bool:
    return path in _JWT_EXEMPT_EXACT or any(path.startswith(p) for p in _JWT_EXEMPT_PREFIXES)


def is_jwt_exempt_request(request: Request) -> bool:
    if request.method == "GET":
        import re

        if re.fullmatch(r"/api/public/thread-shares/[^/]+", request.url.path):
            return True
    return is_jwt_exempt_path(request.url.path)


def get_server(request: Request) -> OctopServer:
    server: OctopServer = request.app.state.octop_server
    if not getattr(server, "_started", False):
        raise OctopError(ErrorCode.INTERNAL_ERROR, "server not started")
    return server


def require_database(server: OctopServer) -> None:
    """Raise when the control-plane DB has not been bound yet (deferred setup)."""
    if not server.database_bound:
        raise OctopError(
            ErrorCode.SETUP_REQUIRED,
            "control-plane database not configured yet",
            status=503,
        )


def extract_raw_token(
    *,
    authorization: str | None = None,
    access_token: str | None = None,
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if access_token:
        return access_token
    return None


def _decode(server: OctopServer, token: str) -> dict[str, Any]:
    assert server.services is not None
    secret = server.services.secret_repo.get("jwt")
    if secret is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "jwt secret missing")
    try:
        payload = decode_token(secret, token)
    except TokenExpired as exc:
        raise OctopError(ErrorCode.TOKEN_EXPIRED, "token expired") from exc
    except InvalidToken as exc:
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid token") from exc
    key_id = payload.get("auth_key_id")
    actor_kind = payload.get("actor_kind")
    if actor_kind == "machine":
        if (
            not isinstance(key_id, str)
            or server.app_runtime is None
            or server.app_runtime.devices is None
        ):
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key session")
        principal = server.app_runtime.devices.agent_access_keys.validate_credential(
            key_id, int(payload["sub"])
        )
        payload["_machine_principal"] = principal
        return payload
    if key_id is not None:
        if (
            not isinstance(key_id, str)
            or server.app_runtime is None
            or server.app_runtime.devices is None
        ):
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid access key session")
        server.app_runtime.devices.access_keys.validate_session(int(payload["sub"]), key_id)
        return payload
    # Browser JWT: require durable sid + auth_version (F06). Legacy tokens without
    # claims must re-login (no infinite compatibility window).
    from octop.infra.auth.sessions import browser_claims_from_payload, validate_browser_session

    claims = browser_claims_from_payload(payload)
    if claims is None:
        raise OctopError(ErrorCode.AUTH_FAILED, "session required; please sign in again")
    sid, av = claims
    validate_browser_session(server, user_id=int(payload["sub"]), sid=sid, av=av)
    return payload


def resolve_user_from_token(server: OctopServer, token: str) -> User:
    payload = _decode(server, token)
    if payload.get("actor_kind") == "machine":
        # Remote ACP uses scoped HTTP polling. Account/device/browser sockets
        # carry broader streams and are never part of the machine surface.
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    assert server.user_manager is not None
    user = server.user_manager.get_by_id(int(payload["sub"]))
    if user is None:
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    return user


def _client_ip_from_request(request: Request) -> str:
    from octop.api.common.client_ip import resolve_client_ip

    return resolve_client_ip(request)


def resolve_machine_from_request(
    request: Request, server: OctopServer, raw: str
) -> MachinePrincipal | None:
    """Authenticate Bearer oaa_ or machine JWT; attach principal on request.state."""
    from octop.infra.auth.agent_access_keys import (
        AGENT_KEY_PREFIX,
        BROWSER_KEY_PREFIX,
        MachinePrincipal,
    )

    cached = getattr(request.state, "octop_machine", None)
    if cached is not None:
        return cast(MachinePrincipal, cached)

    if raw.startswith(BROWSER_KEY_PREFIX):
        raise OctopError(ErrorCode.AUTH_FAILED, "browser access key cannot act as agent bearer")

    if raw.startswith(AGENT_KEY_PREFIX):
        if server.app_runtime is None or server.app_runtime.devices is None:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")
        principal = cast(
            MachinePrincipal,
            server.app_runtime.devices.agent_access_keys.authenticate(
                raw, _client_ip_from_request(request)
            ),
        )
        request.state.octop_machine = principal
        return principal

    # Machine short JWT (optional exchange)
    payload = _decode(server, raw)
    exchanged_principal = payload.get("_machine_principal")
    if exchanged_principal is None:
        return None
    request.state.octop_machine = exchanged_principal
    return cast(MachinePrincipal, exchanged_principal)


def machine_principal_of(request: Request) -> MachinePrincipal | None:
    """Return machine principal if this request was authenticated as machine."""
    return cast(MachinePrincipal | None, getattr(request.state, "octop_machine", None))


def require_human_session(request: Request) -> None:
    """Block machine / access-key JWT from minting new agent keys etc."""
    if machine_principal_of(request) is not None:
        raise OctopError(ErrorCode.FORBIDDEN, "machine credentials cannot manage agent keys")
    raw = extract_raw_token(
        authorization=request.headers.get("authorization"),
        access_token=request.query_params.get("access_token"),
    )
    if raw is None:
        raise OctopError(ErrorCode.AUTH_FAILED, "missing credentials")
    from octop.infra.auth.agent_access_keys import AGENT_KEY_PREFIX

    if raw.startswith(AGENT_KEY_PREFIX):
        raise OctopError(ErrorCode.FORBIDDEN, "machine credentials cannot manage agent keys")
    server = get_server(request)
    payload = _decode(server, raw)
    if payload.get("auth_key_id") is not None or payload.get("actor_kind") == "machine":
        raise OctopError(ErrorCode.FORBIDDEN, "sign in with password or SSO to create keys")


def require_machine_scope(request: Request, scope: str) -> None:
    principal = machine_principal_of(request)
    if principal is None:
        return
    if not principal.has_scope(scope):
        raise OctopError(ErrorCode.FORBIDDEN, f"missing scope {scope}")


def maybe_sliding_renew_token(server: OctopServer, token: str, user: User) -> str | None:
    """Return a fresh access token when ``token`` is past the sliding renew threshold.

    Threshold is one-third of ``access_token_ttl_seconds`` remaining. Active clients
    that pick up ``ACCESS_TOKEN_RESPONSE_HEADER`` stay signed in without re-login.
    """
    from octop.infra.auth.agent_access_keys import AGENT_KEY_PREFIX

    if token.startswith(AGENT_KEY_PREFIX):
        return None
    assert server.services is not None
    payload = _decode(server, token)
    if payload.get("actor_kind") == "machine":
        return None
    ttl = int(server.services.config.access_token_ttl_seconds)
    remaining = int(payload["exp"]) - int(time.time())
    threshold = max(1, int(ttl * _SLIDING_RENEW_REMAINING_FRACTION))
    if remaining >= threshold:
        return None
    secret = server.services.secret_repo.get("jwt")
    if secret is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "jwt secret missing")
    return sign_token(
        secret,
        sub=user.id,
        uname=user.username,
        role=user.role,
        ttl_seconds=ttl,
        auth_key_id=payload.get("auth_key_id"),
        sid=payload.get("sid"),
        av=payload.get("av"),
    )


def authenticate_request(request: Request, server: OctopServer) -> User:
    raw = extract_raw_token(
        authorization=request.headers.get("authorization"),
        access_token=request.query_params.get("access_token"),
    )
    if not raw:
        raise OctopError(ErrorCode.AUTH_FAILED, "missing credentials")
    from octop.infra.auth.agent_access_keys import AGENT_KEY_PREFIX, BROWSER_KEY_PREFIX

    if raw.startswith(BROWSER_KEY_PREFIX):
        raise OctopError(ErrorCode.AUTH_FAILED, "browser access key cannot act as agent bearer")
    if raw.startswith(AGENT_KEY_PREFIX):
        principal = resolve_machine_from_request(request, server, raw)
        assert principal is not None
        assert server.user_manager is not None
        user = server.user_manager.get_by_id(int(principal.owner_user_id))
        if user is None:
            raise OctopError(ErrorCode.USER_DISABLED, "user not active")
        return user
    # JWT path (browser, oak key-session, or machine exchange)
    payload = _decode(server, raw)
    if payload.get("_machine_principal") is not None:
        request.state.octop_machine = payload["_machine_principal"]
    assert server.user_manager is not None
    user = server.user_manager.get_by_id(int(payload["sub"]))
    if user is None:
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    return user


async def current_user(
    request: Request,
    server: OctopServer = Depends(get_server),
    authorization: str | None = Header(None),
    access_token: str | None = Query(None),
) -> User:
    cached = getattr(request.state, "octop_user", None)
    if cached is not None:
        return cast("User", cached)
    raw = extract_raw_token(authorization=authorization, access_token=access_token)
    if not raw:
        raise OctopError(ErrorCode.AUTH_FAILED, "missing credentials")
    return authenticate_request(request, server)


def require_permission(key: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: require the module permission ``key``.

    ``admin`` is bypassed inside ``user_has_permission``. Unknown keys fail
    fast at construction so typos cannot silently grant access.
    """
    if key not in PERMISSIONS:
        raise RuntimeError(f"unknown permission key: {key}")

    async def _dep(user: User = Depends(current_user)) -> User:
        if not user_has_permission(user, key):
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "permission required",
                details={"permission": key},
            )
        return user

    return _dep


def require_admin() -> Callable[..., Awaitable[User]]:
    """Dependency factory: require the admin role (no module key)."""

    async def _dep(user: User = Depends(current_user)) -> User:
        if not user.is_admin:
            raise OctopError(ErrorCode.FORBIDDEN, "admin required")
        return user

    return _dep
