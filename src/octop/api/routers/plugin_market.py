"""Shared dashboard marketplace and private plugin settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from octop.api.deps import current_user, get_server
from octop.infra.plugins.marketplace import PluginMarketplace
from octop.infra.plugins.models import (
    CatalogPlugin,
    CostMeterConfigPatch,
    CostMeterState,
    PluginInstallation,
    PluginInstallationPatch,
)
from octop.infra.server import OctopServer
from octop.infra.users.identity import User

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _market(server: OctopServer) -> PluginMarketplace:
    assert server.services is not None
    return PluginMarketplace(server.services)


@router.get(
    "/catalog", response_model=list[CatalogPlugin], summary="Browse shared dashboard plugins"
)
def catalog(
    response: Response,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> list[CatalogPlugin]:
    response.headers["Cache-Control"] = "no-store"
    return _market(server).catalog(user.id)


@router.put(
    "/mine/{plugin_id}",
    response_model=PluginInstallation,
    summary="Install or enable a plugin for your account",
)
def install(
    plugin_id: str,
    body: PluginInstallationPatch,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> PluginInstallation:
    return _market(server).install(user.id, plugin_id, body)


@router.delete(
    "/mine/{plugin_id}",
    status_code=204,
    summary="Uninstall your plugin and erase its private settings",
)
def uninstall(
    plugin_id: str,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> Response:
    _market(server).uninstall(user.id, plugin_id)
    return Response(status_code=204)


@router.get(
    "/cost-meter/state",
    response_model=CostMeterState,
    summary="Read your quota snapshot and the DeepSeek price clock",
)
def state(
    response: Response,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> CostMeterState:
    response.headers["Cache-Control"] = "no-store"
    return _market(server).state(user.id)


@router.patch(
    "/cost-meter/config",
    response_model=CostMeterState,
    summary="Update your private Go key or subscription expiry",
)
def configure(
    body: CostMeterConfigPatch,
    response: Response,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> CostMeterState:
    response.headers["Cache-Control"] = "no-store"
    return _market(server).configure(user.id, body)


@router.post(
    "/cost-meter/refresh",
    response_model=CostMeterState,
    summary="Refresh your OpenCode Go quota from the official endpoint",
)
async def refresh(
    response: Response,
    server: OctopServer = Depends(get_server),
    user: User = Depends(current_user),
) -> CostMeterState:
    response.headers["Cache-Control"] = "no-store"
    return await _market(server).refresh(user.id)
