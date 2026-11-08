"""Explainable usage signals and quiet-period scheduling, without model calls."""

from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any

from octop.infra.db.repos.threads import ThreadRow
from octop.infra.db.services import RepoBundle


def heat_for(row: ThreadRow, signals: dict[str, Any], now: float) -> dict[str, Any]:
    interactions = int(signals.get("interactions_24h") or 0)
    work = int(signals.get("work_7d") or 0)
    weekly_inputs = int(signals.get("interactions_7d") or 0)
    background = int(signals.get("background_count") or 0)
    attention = int(signals.get("attention_count") or 0)
    last_user = float(signals.get("last_user_at") or 0)
    activity = last_user or row.last_active or row.created_at
    recency = 15 * math.exp(-max(0, now - activity) / 86400) if activity else 0
    score = round(
        min(
            100,
            (40 if background else 28 if attention else 0)
            + 30 * (1 - math.exp(-interactions / 5))
            + 15 * min(1, (work + weekly_inputs / 3) / 5)
            + recency,
        )
    )
    level = (
        "attention"
        if attention
        else "running"
        if background
        else "hot"
        if score >= 50
        else "warm"
        if score >= 25
        else "quiet"
    )
    return {
        "score": score,
        "level": level,
        "interactions_24h": interactions,
        "interactions_7d": int(signals.get("interactions_7d") or 0),
        "work_7d": work,
        "background_count": background,
        "attention_count": attention,
        "last_user_at": last_user,
        "next_overview_at": float(signals.get("next_overview_at") or 0),
        "overview_reason": str(signals.get("overview_reason") or ""),
    }


def overview_due(
    *,
    now: float,
    generated_at: float,
    last_user_at: float,
    score: int,
    active: bool,
    samples: list[float],
) -> tuple[float, str]:
    interval = 1800 if score >= 60 else 900 if score >= 30 else 300
    due = max(
        now,
        generated_at + interval if generated_at else now,
        last_user_at + 300 if last_user_at else now,
    )
    reason = "heat_interval" if due > now else "idle"
    if last_user_at + 300 > now:
        reason = "recent_conversation"
    if active:
        due = max(due, now + 120)
        return due, "answer_running"
    days = {int(stamp // 86400) for stamp in samples}
    if generated_at and len(samples) >= 30 and len(days) >= 3:
        hours = Counter(int(stamp // 3600) % 24 for stamp in samples)
        threshold = sorted(hours.get(hour, 0) for hour in range(24))[5]
        if hours.get(int(due // 3600) % 24, 0) > threshold:
            cap = min(due + 6 * 3600, max(due, generated_at + 86400))
            candidates = [due] + [
                math.floor(due / 3600) * 3600 + offset * 3600 for offset in range(1, 7)
            ]
            candidates = [stamp for stamp in candidates if due <= stamp <= cap]
            chosen = min(
                candidates, key=lambda stamp: (hours.get(int(stamp // 3600) % 24, 0), stamp)
            )
            if chosen > due:
                due, reason = chosen, "quiet_window"
    return due, reason


class ThreadHeatService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos

    def list(
        self, owner: int, agent: str, limit: int = 50
    ) -> list[tuple[ThreadRow, dict[str, Any]]]:
        now = time.time()
        rows = self.repos.thread_repo.list_by_agent_user(agent_id=agent, user_id=owner, limit=None)
        signals = self.repos.thread_activity_repo.signals(owner, agent, now)
        ranked = [(row, heat_for(row, signals.get(row.thread_id, {}), now)) for row in rows]
        ranked.sort(
            key=lambda item: (
                item[0].pinned,
                item[1]["score"],
                item[0].last_active or item[0].created_at,
                item[0].thread_id,
            ),
            reverse=True,
        )
        return ranked[: max(0, limit)]

    def due(
        self, owner: int, row: ThreadRow, generated_at: float, active: bool
    ) -> tuple[float, str]:
        now = time.time()
        signal = self.repos.thread_activity_repo.signals(owner, row.agent_id, now).get(
            row.thread_id, {}
        )
        heat = heat_for(row, signal, now)
        return overview_due(
            now=now,
            generated_at=generated_at,
            last_user_at=heat["last_user_at"],
            score=heat["score"],
            active=active,
            samples=self.repos.thread_activity_repo.profile(owner, now),
        )
