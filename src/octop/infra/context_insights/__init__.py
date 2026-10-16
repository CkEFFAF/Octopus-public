"""Read-only Context Insights shared by Dashboard and native tools."""

from octop.infra.context_insights.dto import SCHEMA_VERSION
from octop.infra.context_insights.mapping import map_event_kind
from octop.infra.context_insights.service import ContextInsightsService

__all__ = ["ContextInsightsService", "SCHEMA_VERSION", "map_event_kind"]
