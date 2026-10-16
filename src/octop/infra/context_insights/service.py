"""Single read-only Context Insights aggregator (DEC-02 / DEC-03)."""

from __future__ import annotations

from typing import Any

from octop.infra.agents.threads.context_breakdown import SEGMENT_KEYS, compute_context_breakdown
from octop.infra.context_insights.mapping import map_event_kind
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.history.trajectory.metrics import aggregate_metrics


class ContextInsightsService:
    """Shared by Dashboard consumers and native `context_*` tools."""

    def __init__(self, registry: Any, repos: Any, *, execution: Any | None = None) -> None:
        self._registry = registry
        self._repos = repos
        self._execution = execution

    async def inspect(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        include: list[str] | None = None,
        trend_limit: int = 20,
    ) -> dict[str, Any]:
        wanted = set(include or ("stats", "breakdown", "trend", "execution"))
        out: dict[str, Any] = {
            "agent_id": agent_id,
            "thread_id": thread_id,
            "meter_source": "context_usage",
        }
        if "breakdown" in wanted or "stats" in wanted:
            breakdown = await self._breakdown(agent_id, thread_id)
            if "breakdown" in wanted:
                out["breakdown"] = breakdown
        if "stats" in wanted:
            events = self._repos.trajectory_event_repo.list_before(
                thread_id, before_seq=None, limit=2000, kinds=None
            )
            metrics = aggregate_metrics(events)
            out["stats"] = {
                "turns": metrics.turns,
                "steps": metrics.steps,
                "tool_calls": metrics.tool_calls,
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "cache_hit_ratio": metrics.cache_hit_ratio,
                "llm_duration_ms": metrics.llm_duration_ms,
                "tool_duration_ms": metrics.tool_duration_ms,
                "ttft_avg_ms": metrics.ttft_avg_ms,
                # No pricing SoT — callers must show "—" (DEC-I05).
                "cost": None,
                "gaps": ["cost_no_pricing_sot"],
            }
            if "breakdown" in wanted:
                out["stats"]["used_tokens"] = breakdown["used_tokens"]
                out["stats"]["max_tokens"] = breakdown["max_tokens"]
        if "trend" in wanted:
            out["trend"] = self._trend_points(thread_id, limit=max(1, min(int(trend_limit), 100)))
        if "execution" in wanted:
            out["execution"] = self._execution_summary(owner, thread_id)
        return out

    async def events(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        kinds: list[str] | None = None,
        before_seq: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        del owner, agent_id  # ACL enforced by caller
        size = max(1, min(int(limit), 100))
        mapped_filter = {k.strip().lower() for k in (kinds or []) if k and k.strip()}
        # Over-fetch when filtering so has_more reflects another *matching* row,
        # not merely that the unfiltered window was full (false positive).
        fetch_limit = size + 1 if not mapped_filter else min(500, max((size + 1) * 8, 80))
        raw = self._repos.trajectory_event_repo.list_before(
            thread_id, before_seq=before_seq, limit=fetch_limit, kinds=None
        )
        # list_before returns oldest→newest. Compute real deltas vs prior step
        # with input_tokens; never treat absolute input_tokens as delta.
        token_delta_by_id: dict[str, int | None] = {}
        prev_tokens: int | None = None
        for event in raw:
            raw_tokens = event.payload.get("input_tokens")
            if raw_tokens is None:
                token_delta_by_id[event.event_id] = None
                continue
            try:
                tokens = int(raw_tokens)
            except (TypeError, ValueError):
                token_delta_by_id[event.event_id] = None
                continue
            token_delta_by_id[event.event_id] = (
                None if prev_tokens is None else tokens - prev_tokens
            )
            prev_tokens = tokens

        # P1 gap: run_event kinds (model/device/workflow) are not merged into
        # this trajectory page yet — see mapping.map_event_kind(source="run_event")
        # and spec 0020 §5.2 P1 "配置变更 → Events".
        items: list[dict[str, Any]] = []
        saw_extra_match = False
        for event in reversed(raw):
            mapped = map_event_kind(event.kind, payload=event.payload, source="trajectory")
            if mapped_filter and mapped not in mapped_filter and event.kind not in mapped_filter:
                continue
            if len(items) >= size:
                saw_extra_match = True
                break
            items.append(
                {
                    "event_id": event.event_id,
                    "seq": event.seq,
                    "ts": event.ts,
                    "mapped_kind": mapped,
                    "raw_kind": event.kind,
                    "summary": event.summary,
                    "token_delta": token_delta_by_id.get(event.event_id),
                    "producer": event.payload.get("producer") or event.payload.get("source"),
                    "request_seq": event.request_seq,
                }
            )
        has_more = saw_extra_match
        next_before = items[-1]["seq"] if has_more and items else None
        return {"events": items, "has_more": has_more, "next_before_seq": next_before}

    async def file_ops(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        upto_request_seq: int | None = None,
        path_prefix: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Aggregate read/write/search path counts when payload fields exist."""
        size = max(1, min(int(limit), 100))
        gaps: list[str] = []
        files: dict[str, dict[str, Any]] = {}
        events = RunEventRepo(self._repos.db).list(owner, agent_id, thread_id, limit=500)
        prefix = (path_prefix or "").strip()
        matched = 0
        for event in events:
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if upto_request_seq is not None:
                req = payload.get("request_seq") or payload.get("seq")
                try:
                    if req is not None and int(req) > int(upto_request_seq):
                        continue
                except (TypeError, ValueError):
                    pass
            path = _file_path(payload)
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue
            op = _file_op(event.get("kind"), payload)
            if op is None:
                continue
            row = files.setdefault(path, {"path": path, "reads": 0, "writes": 0, "searches": 0})
            row[op] = int(row.get(op, 0) or 0) + 1
            for key, alias in (
                ("lines_added", "lines_added"),
                ("lines_removed", "lines_removed"),
                ("added", "lines_added"),
                ("removed", "lines_removed"),
            ):
                if key in payload and alias not in row:
                    try:
                        row[alias] = int(payload[key])
                    except (TypeError, ValueError):
                        gaps.append(f"non_int:{alias}")
            matched += 1
        if matched == 0:
            gaps.append("file_activity_aggregation_sparse")
        ordered = sorted(files.values(), key=lambda r: r["path"])[:size]
        truncated = len(files) > size
        return {"files": ordered, "truncated": truncated, "gaps": sorted(set(gaps))}

    async def dashboard_summary(
        self,
        *,
        owner: int,
        window: str = "last_30d",
        query: str = "",
        limit: int = 50,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Cross-session Insights skeleton (Face B / DEC-I02 / OQ-I10).

        KPI card slots + searchable Sessions list. Cost / balance / tool_calls /
        active_time stay honest gaps (``—`` / ``gaps``) until pricing SoT lands.
        """
        usage_repo = getattr(self._repos, "usage_repo", None)
        thread_repo = getattr(self._repos, "thread_repo", None)
        gaps: list[str] = [
            "cost_no_pricing_sot",
            "balance_no_provider_sot",
            "tool_calls_cross_session_p1",
            "active_time_cross_session_p1",
        ]
        if usage_repo is None:
            return {
                "window": window,
                "kpi": {
                    "active_sessions": 0,
                    "total_sessions": 0,
                    "total_tokens": 0,
                    "turns": 0,
                    "cache_hit_percent": None,
                    "cost": None,
                    "tool_calls": None,
                    "active_time_ms": None,
                    "balance": None,
                },
                "by_day": [],
                "sessions": [],
                "gaps": gaps + ["usage_repo_missing"],
            }

        summary = usage_repo.summary(
            user_id=owner,
            window=window,
            granularity="by_day",
            timezone=timezone,
        )
        rollup = usage_repo.thread_rollup(
            user_id=owner,
            window=window,
            timezone=timezone,
            limit=max(1, min(int(limit), 200)),
        )
        active = usage_repo.count_active_threads(user_id=owner, window=window, timezone=timezone)
        total_sessions = 0
        titles: dict[str, Any] = {}
        if thread_repo is not None:
            try:
                total_sessions = int(thread_repo.count_by_user(user_id=owner))
            except Exception:
                total_sessions = active
            try:
                titles = thread_repo.get_many([str(r["thread_id"]) for r in rollup])
            except Exception:
                titles = {}
        else:
            total_sessions = active
            gaps.append("thread_repo_missing")

        q = (query or "").strip().lower()
        sessions: list[dict[str, Any]] = []
        for row in rollup:
            thread_id = str(row["thread_id"])
            meta = titles.get(thread_id) if isinstance(titles, dict) else None
            title = None
            agent_id = str(row["agent_id"])
            last_active = int(row.get("last_ts") or 0)
            if meta is not None:
                title = getattr(meta, "title", None)
                agent_id = getattr(meta, "agent_id", None) or agent_id
                last_active = int(getattr(meta, "last_active", 0) or last_active)
            hay = f"{title or ''} {thread_id} {agent_id}".lower()
            if q and q not in hay:
                continue
            cache_read = int(row.get("cache_read_tokens") or 0)
            input_tokens = int(row.get("input_tokens") or 0)
            cache_hit = round(cache_read / input_tokens * 100, 2) if input_tokens else None
            sessions.append(
                {
                    "thread_id": thread_id,
                    "agent_id": agent_id,
                    "title": title or thread_id,
                    "total_tokens": int(row.get("total_tokens") or 0),
                    "input_tokens": input_tokens,
                    "output_tokens": int(row.get("output_tokens") or 0),
                    "turns": int(row.get("turns") or 0),
                    "model_calls": int(row.get("model_calls") or 0),
                    "cache_hit_percent": cache_hit,
                    "last_active": last_active,
                    # Honest: no pricing SoT
                    "cost": None,
                    "steps": None,
                }
            )

        by_day = [
            {
                "key": b["key"],
                "label": b["label"],
                "total_tokens": int(b.get("total_tokens") or 0),
                "turns": int(b.get("turns") or 0),
                # cost column deliberately omitted / null
                "cost": None,
            }
            for b in (summary.get("buckets") or [])
        ]

        return {
            "window": window,
            "range_start": summary.get("range_start"),
            "range_end": summary.get("range_end"),
            "kpi": {
                "active_sessions": active,
                "total_sessions": total_sessions,
                "total_tokens": int(summary.get("total_tokens") or 0),
                "turns": int(summary.get("turns") or 0),
                "cache_hit_percent": summary.get("cache_hit_percent"),
                "model_calls": int(summary.get("model_calls") or 0),
                "cost": None,
                "tool_calls": None,
                "active_time_ms": None,
                "balance": None,
            },
            "by_day": by_day,
            "sessions": sessions,
            "gaps": gaps,
        }

    async def _breakdown(self, agent_id: str, thread_id: str) -> dict[str, Any]:
        max_tokens = 128_000
        resolve = getattr(self._registry, "resolve_context_max_tokens", None)
        if callable(resolve):
            try:
                max_tokens = int(resolve(agent_id, fallback=128_000) or 128_000)
            except Exception:
                max_tokens = 128_000
        result = await compute_context_breakdown(
            self._registry,
            agent_id=agent_id,
            thread_id=thread_id,
            max_tokens=max_tokens,
            usage_repo=getattr(self._repos, "usage_repo", None),
        )
        return {
            "max_tokens": result.max_tokens,
            "used_tokens": result.used_tokens,
            "segments": [
                {"key": key, "tokens": result.segments.get(key, 0)}
                for key in SEGMENT_KEYS
                if result.segments.get(key, 0) > 0
            ],
        }

    def _trend_points(self, thread_id: str, *, limit: int) -> list[dict[str, Any]]:
        events = self._repos.trajectory_event_repo.list_before(
            thread_id, before_seq=None, limit=max(limit * 4, 80), kinds=None
        )
        points: list[dict[str, Any]] = []
        prev_tokens: int | None = None
        for event in events:
            raw = event.payload.get("input_tokens")
            if raw is None:
                continue
            try:
                tokens = int(raw)
            except (TypeError, ValueError):
                continue
            if tokens <= 0:
                continue
            marks: list[str] = []
            mapped = map_event_kind(event.kind, payload=event.payload)
            if mapped in {"compact", "prune"} or event.kind == "compacted":
                marks.append("scissors")
            delta = None if prev_tokens is None else tokens - prev_tokens
            prev_tokens = tokens
            points.append(
                {
                    "seq": event.seq,
                    "request_seq": event.request_seq,
                    "input_tokens": tokens,
                    "delta_tokens": delta,
                    "kind_marks": marks,
                    "raw_kind": event.kind,
                    "mapped_kind": mapped,
                    "event_id": event.event_id,
                    "turn_id": event.turn_id,
                }
            )
        return points[-limit:]

    def _execution_summary(self, owner: int, thread_id: str) -> dict[str, Any] | None:
        if self._execution is None:
            return None
        try:
            selection = self._execution.selection(owner, thread_id)
        except Exception:
            return None
        if not isinstance(selection, dict):
            return None
        return {
            "target_kind": selection.get("target_kind"),
            "device_id": selection.get("device_id"),
            "working_dir": selection.get("working_dir"),
            "work_mode": selection.get("work_mode"),
        }


def _file_path(payload: dict[str, Any]) -> str | None:
    for key in ("path", "file_path", "target_path", "source_path", "destination"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


_READ_TOOLS = frozenset({"read_file", "read", "cat", "open_file", "read_text", "read_bytes"})
_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "write",
        "apply_patch",
        "str_replace",
        "create_file",
        "delete_file",
    }
)
_SEARCH_TOOLS = frozenset(
    {"grep", "glob", "search", "find", "rg", "codebase_search", "file_search"}
)


def _tool_name_tokens(name: str) -> set[str]:
    """Split tool/kind identifiers into whole tokens (avoid 'open'∈'openai')."""
    cleaned = name.strip().lower()
    if not cleaned:
        return set()
    parts = {cleaned}
    for sep in ("_", "-", ".", "/", ":"):
        if sep in cleaned:
            parts.update(p for p in cleaned.split(sep) if p)
    return parts


def _file_op(kind: Any, payload: dict[str, Any]) -> str | None:
    name = str(payload.get("tool") or payload.get("name") or kind or "")
    tokens = _tool_name_tokens(name)
    if tokens & _READ_TOOLS:
        return "reads"
    if tokens & _WRITE_TOOLS:
        return "writes"
    if tokens & _SEARCH_TOOLS:
        return "searches"
    op = str(payload.get("op") or payload.get("operation") or "").strip().lower()
    if op in {"read", "reads"}:
        return "reads"
    if op in {"write", "writes", "edit"}:
        return "writes"
    if op in {"search", "searches"}:
        return "searches"
    return None
