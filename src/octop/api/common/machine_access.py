"""Explicit HTTP surface for machine credentials; everything else is denied."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request

from octop.api.deps import machine_principal_of
from octop.infra.auth.agent_access_keys import AgentAccessKeyService
from octop.infra.errors import ErrorCode, OctopError


def require_machine_http_access(request: Request, server: Any) -> None:
    principal = machine_principal_of(request)
    if principal is None:
        return
    service: AgentAccessKeyService = server.app_runtime.devices.agent_access_keys
    path, method = request.url.path, request.method
    if "as_user" in request.query_params:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    if method == "GET" and path == "/api/auth/agent-access-keys/identity":
        return
    if path == "/api/work-items" and method in {"GET", "POST"}:
        service.require_scope(principal, "tasks.read" if method == "GET" else "tasks.create")
        return
    task = re.fullmatch(
        r"/api/work-items/([^/]+)(?:/(progress|events|inputs|cancel|permissions))?", path
    )
    if task:
        action = task[2]
        scope = (
            "tasks.read"
            if method == "GET" and action in {None, "progress", "events", "inputs"}
            else "tasks.input"
            if method == "POST" and action in {"inputs", "permissions"}
            else "tasks.cancel"
            if method == "POST" and action == "cancel"
            else None
        )
        if scope is not None:
            service.require_scope(principal, scope)
            service.require_task(principal, task[1])
            return
    create = re.fullmatch(r"/api/agents/([^/]+)/threads", path)
    if create and method == "POST":
        service.require_scope(principal, "tasks.create")
        service.require_expert(principal, create[1])
        return
    thread = re.fullmatch(r"/api/agents/([^/]+)/threads/([^/]+)/history", path)
    if thread and method == "GET":
        service.require_scope(principal, "tasks.read")
        service.require_thread(principal, thread[1], thread[2])
        return
    resource = re.fullmatch(
        r"/api/agents/([^/]+)/threads/([^/]+)/resources/([^/]+)(?:/content)?", path
    )
    if resource and method == "GET":
        service.require_scope(principal, "resources.read")
        service.require_thread(principal, resource[1], resource[2])
        return
    raise OctopError.localized(ErrorCode.FORBIDDEN)
