"""Settings and session routing for scheduled reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from octop.infra.gateway.threads import ThreadRegistry


@dataclass(frozen=True)
class ReportOptions:
    new_conversation: bool = False
    include_previous: bool = False
    previous_count: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ReportOptions:
        new_conversation = value.get("new_conversation", False)
        include_previous = value.get("include_previous", False)
        previous_count = value.get("previous_count", 1)
        if not isinstance(new_conversation, bool) or not isinstance(include_previous, bool):
            raise ValueError("report switches must be boolean")
        if isinstance(previous_count, bool) or not isinstance(previous_count, int):
            raise ValueError("previous report count must be an integer")
        if not 1 <= previous_count <= 30:
            raise ValueError("previous report count must be between 1 and 30")
        return cls(new_conversation, include_previous, previous_count)

    def as_dict(self) -> dict[str, Any]:
        return {
            "new_conversation": self.new_conversation,
            "include_previous": self.include_previous,
            "previous_count": self.previous_count,
        }


def report_session_key(*, agent_id: str, user_id: int, cron_id: str) -> str:
    return ThreadRegistry.make_key(
        agent_id=agent_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        channel_subject_id=str(user_id),
        channel_chat_type=f"report-{cron_id}",
    )


def report_options(row: Any) -> ReportOptions | None:
    if getattr(row, "kind", "user") != "daily_report":
        return None
    raw = (row.meta or {}).get("daily_report")
    if not isinstance(raw, dict):
        raise ValueError("daily report settings are missing")
    return ReportOptions.from_dict(raw)
