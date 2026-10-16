"""Context Insights dashboard API (spec 0020.2 Face B).

GET /api/context-insights/dashboard → cross-session KPI + Sessions list
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from octop.api.deps import current_user, get_server
from octop.infra.context_insights.service import ContextInsightsService
from octop.infra.errors import ErrorCode, OctopError

router = APIRouter()

_ALLOWED_WINDOWS = frozenset({"last_24h", "last_7d", "last_30d", "all"})


def _timezone(server: Any) -> str:
    config = getattr(server, "config", None)
    tz = getattr(config, "default_timezone", None) if config is not None else None
    return str(tz or "UTC")


@router.get("/context-insights/dashboard")
async def context_insights_dashboard(
    window: str = Query("last_30d"),
    q: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Cross-session Insights skeleton — same service as future tools."""
    if window not in _ALLOWED_WINDOWS:
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            f"unsupported window {window!r}; expected one of {sorted(_ALLOWED_WINDOWS)}",
            status=400,
        )
    services = getattr(server, "services", None)
    if services is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "services unavailable")
    registry = None
    runtime = getattr(server, "app_runtime", None)
    if runtime is not None:
        registry = getattr(runtime, "agent_registry", None)
    insights = ContextInsightsService(registry, services)
    return await insights.dashboard_summary(
        owner=int(user.id),
        window=window,
        query=q,
        limit=limit,
        timezone=_timezone(server),
    )
