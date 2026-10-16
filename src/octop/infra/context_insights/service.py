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
        out: dict[str, Any] = {"agent_id": agent_id, "thread_id": thread_id, "meter_source": "context_usage"}
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
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "cache_hit_ratio": metrics.cache_hit_ratio,
                "llm_duration_ms": metrics.llm_duration_ms,
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
        # Fetch one extra to compute has_more; filter by mapped kind after.
        raw = self._repos.trajectory_event_repo.list_before(
            thread_id, before_seq=before_seq, limit=size + 1, kinds=None
        )
        mapped_filter = {k.strip().lower() for k in (kinds or []) if k and k.strip()}
        items: list[dict[str, Any]] = []
        # Prefer newest-first presentation for tools.
        newest_first = list(reversed(raw))
        for event in newest_first:
            mapped = map_event_kind(event.kind, payload=event.payload, source="trajectory")
            if mapped_filter and mapped not in mapped_filter and event.kind not in mapped_filter:
                continue
            token_delta = None
            if event.payload.get("input_tokens") is not None:
                try:
                    token_delta = int(event.payload.get("input_tokens") or 0)
                except (TypeError, ValueError):
                    token_delta = None
            items.append(
                {
                    "event_id": event.event_id,
                    "seq": event.seq,
                    "ts": event.ts,
                    "mapped_kind": mapped,
                    "raw_kind": event.kind,
                    "summary": event.summary,
                    "token_delta": token_delta,
                    "producer": event.payload.get("producer") or event.payload.get("source"),
                    "request_seq": event.request_seq,
                }
            )
            if len(items) >= size:
                break
        has_more = len(newest_first) > size
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
            row = files.setdefault(
                path, {"path": path, "reads": 0, "writes": 0, "searches": 0}
            )
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


def _file_op(kind: Any, payload: dict[str, Any]) -> str | None:
    name = str(payload.get("tool") or payload.get("name") or kind or "").lower()
    if any(token in name for token in ("read_file", "read", "cat", "open")):
        return "reads"
    if any(token in name for token in ("write_file", "edit_file", "write", "apply_patch")):
        return "writes"
    if any(token in name for token in ("grep", "glob", "search", "find")):
        return "searches"
    op = str(payload.get("op") or payload.get("operation") or "").lower()
    if op in {"read", "reads"}:
        return "reads"
    if op in {"write", "writes", "edit"}:
        return "writes"
    if op in {"search", "searches"}:
        return "searches"
    return None

