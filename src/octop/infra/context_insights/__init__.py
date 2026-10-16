"""Read-only Context Insights shared by Dashboard and native tools."""

from octop.infra.context_insights.mapping import map_event_kind
from octop.infra.context_insights.service import ContextInsightsService

__all__ = ["ContextInsightsService", "map_event_kind"]
