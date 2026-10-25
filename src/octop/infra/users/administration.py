"""Authority boundaries for delegated account and role administration."""

from __future__ import annotations

from collections.abc import Sequence

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role, User
from octop.infra.users.permissions import validate_permission_keys


def assert_can_assign(actor: User, permissions: Sequence[str]) -> None:
    """Validate permissions before writing; delegates can only grant their own keys."""
    try:
        keys = validate_permission_keys(list(permissions))
    except ValueError as exc:
        raise OctopError(ErrorCode.FORBIDDEN, str(exc), status=400) from exc
    if actor.is_admin:
        return
    missing = sorted(set(keys) - set(actor.permissions or []))
    if missing:
        raise OctopError(
            ErrorCode.FORBIDDEN,
            "cannot grant permissions you do not hold",
            details={"missing": missing},
        )


def assert_can_manage_account(actor: User, *, role: str, permissions: Sequence[str]) -> None:
    """Password resets and other writes cannot control a more privileged identity."""
    if actor.is_admin:
        return
    if role == Role.ADMIN:
        raise OctopError(ErrorCode.FORBIDDEN, "only an administrator can manage administrators")
    assert_can_assign(actor, permissions)
