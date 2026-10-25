"""0038 F01 stdio MCP execution authorization."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from octop.infra.connectors.execution_auth import (
    authorize_mcp_execution,
    authorize_stdio_mcp_spec,
)
from octop.infra.errors import ErrorCode, OctopError


def test_ordinary_user_denied_stdio_on_control_server() -> None:
    user = SimpleNamespace(role="user", is_admin=False)
    with pytest.raises(OctopError) as ei:
        authorize_mcp_execution(user, transport="stdio", location="control_server")
    assert ei.value.code == ErrorCode.FORBIDDEN


def test_admin_allowed_stdio_on_control_server() -> None:
    admin = SimpleNamespace(role="admin", is_admin=True)
    authorize_mcp_execution(admin, transport="stdio", location="control_server")


def test_ordinary_user_allowed_streamable_http() -> None:
    user = SimpleNamespace(role="user", is_admin=False)
    authorize_stdio_mcp_spec(
        user,
        {"transport": "streamable_http", "url": "https://example.invalid"},
        location="control_server",
    )


def test_ordinary_user_allowed_stdio_on_user_device() -> None:
    user = SimpleNamespace(role="user", is_admin=False)
    authorize_mcp_execution(user, transport="stdio", location="user_device")
