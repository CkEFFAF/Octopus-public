"""Authenticated Graph authoring plus a separate scoped script event ingress."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import Field

from octop.api.deps import current_user, get_server
from octop.infra.workflow_graphs.models import GraphDefinition, Issue, Model, validate_graph
from octop.infra.workflow_graphs.responses import (
    ActivationSummary,
    ActivationView,
    GraphSummary,
    ResultPage,
    RunView,
)
from octop.infra.workflow_graphs.service import (
    GraphView,
    Page,
    RunControl,
    SaveGraph,
    StartRun,
    WorkflowGraphService,
)

router = APIRouter(prefix="/workflow-graphs")


def service(server: Any = Depends(get_server)) -> WorkflowGraphService:
    return cast(WorkflowGraphService, server.app_runtime.workflow_graphs)


def checked[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Revision(Model):
    revision: int = Field(ge=1)


class EventBody(Model):
    event_id: str = Field(min_length=1, max_length=160)
    data: Any = None


class ValidationReport(Model):
    definition: GraphDefinition
    issues: list[Issue]


@router.post("/normalize", response_model=ValidationReport)
async def normalize(body: GraphDefinition, user: Any = Depends(current_user)) -> ValidationReport:
    return ValidationReport(definition=body, issues=validate_graph(body))


@router.get("", response_model=ResultPage[GraphSummary])
async def list_graphs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> Page:
    return graphs.list(user.id, limit, offset)


@router.put("", response_model=GraphView)
async def save(
    body: SaveGraph,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> GraphView:
    return checked(lambda: graphs.save(user.id, body))


@router.post("/validate", response_model=list[Issue])
async def validate(body: GraphDefinition, user: Any = Depends(current_user)) -> list[Issue]:
    return validate_graph(body)


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(
    run_id: str, user: Any = Depends(current_user), graphs: WorkflowGraphService = Depends(service)
) -> dict[str, Any]:
    return graphs.run(user.id, run_id)


@router.get("/runs/{run_id}/timeline", response_model=ResultPage[ActivationSummary])
async def timeline(
    run_id: str,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> Page:
    return graphs.timeline(user.id, run_id, limit, offset)


@router.post("/runs/{run_id}/control", response_model=RunView)
async def control(
    run_id: str,
    body: RunControl,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    return checked(lambda: graphs.control(user.id, run_id, body))


@router.get("/activations/{identity}", response_model=ActivationView)
async def inspect(
    identity: str,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    return graphs.inspect(user.id, identity)


@router.post("/activations/{identity}/retry", response_model=RunView)
async def retry(
    identity: str,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    return checked(lambda: graphs.retry(user.id, identity))


@router.post("/activations/{identity}/reconcile", response_model=ActivationView)
async def reconcile(
    identity: str,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    try:
        return await graphs.runner.reconcile(user.id, identity)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{graph_id}", response_model=GraphView)
async def get_graph(
    graph_id: str,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> GraphView:
    return graphs.get(user.id, graph_id)


@router.post("/{graph_id}/publish", response_model=GraphView)
async def publish(
    graph_id: str,
    body: Revision,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> GraphView:
    return checked(lambda: graphs.publish(user.id, graph_id, body.revision))


@router.get("/{graph_id}/versions/{revision}", response_model=GraphDefinition)
async def version(
    graph_id: str,
    revision: int,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> GraphDefinition:
    return graphs.published_version(user.id, graph_id, revision)


@router.post("/runs/{run_id}/cancel-jobs")
async def cancel_jobs(
    run_id: str, user: Any = Depends(current_user), graphs: WorkflowGraphService = Depends(service)
) -> dict[str, Any]:
    return await graphs.runner.cancel_jobs(user.id, run_id)


@router.post("/{graph_id}/archive")
async def archive(
    graph_id: str,
    body: Revision,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, bool]:
    checked(lambda: graphs.archive(user.id, graph_id, body.revision))
    return {"archived": True}


@router.post("/{graph_id}/start", response_model=RunView)
async def start(
    graph_id: str,
    body: StartRun,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    try:
        return await graphs.start(user.id, graph_id, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{graph_id}/runs", response_model=ResultPage[RunView])
async def runs(
    graph_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> Page:
    return graphs.runs(user.id, graph_id, limit, offset)


@router.post("/{graph_id}/capability")
async def capability(
    graph_id: str,
    revoke: bool = False,
    user: Any = Depends(current_user),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, str]:
    return checked(lambda: graphs.capability(user.id, graph_id, revoke))


@router.post("/{graph_id}/events", status_code=202, response_model=RunView)
async def fire(
    graph_id: str,
    request: Request,
    token: str = Header("", alias="X-Octop-Graph-Token"),
    graphs: WorkflowGraphService = Depends(service),
) -> dict[str, Any]:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 12288:
            raise HTTPException(413, "Event body is too large")
    try:
        body = EventBody.model_validate_json(raw)
        return await graphs.fire(graph_id, token, body.event_id, body.data)
    except ValueError as exc:
        raise HTTPException(422, "Invalid graph event data") from exc
