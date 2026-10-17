"""Single read-only Context Insights aggregator (0020 DEC-02/03 + 0021 P0-A/B)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from octop.infra.agents.threads.context_breakdown import SEGMENT_KEYS, compute_context_breakdown
from octop.infra.context_insights.dto import (
    SCHEMA_VERSION,
    coverage_block,
    resolved_scope,
    source_ref,
    utc_rfc3339,
)
from octop.infra.context_insights.mapping import map_event_kind
from octop.infra.db.repos.execution import ExecutionContextRepo
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.execution.inspection import RequestInspectionService
from octop.infra.history.trajectory.metrics import aggregate_metrics

COMPATIBILITY_CAPACITY_TOKENS = 128_000


class ContextInsightsService:
    """Shared by Dashboard consumers and native `context_*` tools."""

    def __init__(self, registry: Any, repos: Any, *, execution: Any | None = None) -> None:
        self._registry = registry
        self._repos = repos
        self._execution = execution

    def _require_thread(self, owner: int, agent_id: str, thread_id: str) -> Any:
        row = self._repos.thread_repo.get(thread_id)
        if row is None or int(row.user_id) != int(owner) or row.agent_id != agent_id:
            from octop.infra.errors import ErrorCode, OctopError

            raise OctopError(ErrorCode.NOT_FOUND, "context insights unavailable")
        return row

    async def inspect(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        include: list[str] | None = None,
        trend_limit: int = 20,
    ) -> dict[str, Any]:
        self._require_thread(owner, agent_id, thread_id)
        wanted = set(include or ("stats", "breakdown", "trend", "execution", "meters"))
        as_of = utc_rfc3339()
        scope = resolved_scope(owner_user_id=owner, agent_id=agent_id, thread_id=thread_id)
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "resolved_scope": scope,
            "as_of": as_of,
            "revision": None,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "meter_source": "context_usage",
        }

        traj_meta = self._trajectory_coverage(thread_id)
        out["coverage"] = traj_meta["coverage"]
        out["revision"] = traj_meta.get("revision")

        breakdown: dict[str, Any] | None = None
        if "breakdown" in wanted or "stats" in wanted or "meters" in wanted:
            breakdown = await self._breakdown(agent_id, thread_id)
            if "breakdown" in wanted:
                out["breakdown"] = breakdown
                out["window"] = {
                    "used_tokens": breakdown["used_tokens"],
                    "capacity_tokens": breakdown.get("capacity_tokens"),
                    "capacity_source": breakdown["capacity_source"],
                    "compatibility_capacity_tokens": breakdown["compatibility_capacity_tokens"],
                    "max_tokens": breakdown["max_tokens"],
                    "segments": breakdown["segments"],
                }

        if "stats" in wanted or "meters" in wanted:
            events = self._repos.trajectory_event_repo.list_before(
                thread_id, before_seq=None, limit=2000, kinds=None
            )
            metrics = aggregate_metrics(events)
            model_requests = self._count_model_requests(owner, agent_id, thread_id)
            human_turns = sum(1 for e in events if e.kind == "user")
            trajectory_events = len(events)
            tool_counts = self._tool_count_fields(events)
            stats = {
                # DEC-T15 preferred fields
                "model_requests": model_requests,
                "human_turns": human_turns,
                "trajectory_events": trajectory_events,
                # legacy aliases (aggregate_metrics口径)
                "turns": metrics.turns,
                "steps": metrics.steps,
                "legacy_alias": {
                    "turns": "human_turns≈kind==user event count",
                    "steps": "trajectory_events≈len(events)",
                },
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "cache_hit_ratio": metrics.cache_hit_ratio,
                "llm_duration_ms": metrics.llm_duration_ms,
                "tool_schema_count": tool_counts["tool_schema_count"],
                "logical_call_count": tool_counts["logical_call_count"],
                "attempt_count": tool_counts["attempt_count"],
            }
            if breakdown is not None:
                stats["used_tokens"] = breakdown["used_tokens"]
                stats["max_tokens"] = breakdown["max_tokens"]
            if "stats" in wanted:
                out["stats"] = stats

        if "meters" in wanted or "stats" in wanted:
            out["meters"] = self._meters(
                owner=owner,
                agent_id=agent_id,
                thread_id=thread_id,
                breakdown=breakdown,
            )

        if "trend" in wanted:
            out["trend"] = self._trend_points(thread_id, limit=max(1, min(int(trend_limit), 100)))
        if "execution" in wanted:
            out["execution"] = {
                "current_selection": self._execution_summary(owner, thread_id),
                "configured_defaults": None,
            }
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
        self._require_thread(owner, agent_id, thread_id)
        size = max(1, min(int(limit), 100))
        mapped_filter = {k.strip().lower() for k in (kinds or []) if k and k.strip()}
        fetch_limit = size + 1 if not mapped_filter else min(500, max((size + 1) * 8, 80))
        raw = self._repos.trajectory_event_repo.list_before(
            thread_id, before_seq=before_seq, limit=fetch_limit, kinds=None
        )
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

        # P1 gap: run_event kinds not merged — do not pretend otherwise.
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
                    "turn_id": event.turn_id,
                    "source_ref": source_ref("trajectory", event.event_id),
                    "status": _tool_status(event),
                }
            )
        has_more = saw_extra_match
        next_before = items[-1]["seq"] if has_more and items else None
        traj = self._trajectory_coverage(thread_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "resolved_scope": resolved_scope(
                owner_user_id=owner, agent_id=agent_id, thread_id=thread_id
            ),
            "as_of": utc_rfc3339(),
            "events": items,
            "has_more": has_more,
            "next_before_seq": next_before,
            "coverage": traj["coverage"],
        }

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
        self._require_thread(owner, agent_id, thread_id)
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
        level = "partial" if gaps or truncated else ("complete" if matched else "unavailable")
        return {
            "schema_version": SCHEMA_VERSION,
            "files": ordered,
            "truncated": truncated,
            "gaps": sorted(set(gaps)),
            "coverage": coverage_block(
                level=level,  # type: ignore[arg-type]
                reason_codes=list(dict.fromkeys(gaps)),
                source="run_event",
                quality="heuristic_path_aggregate",
            ),
        }

    async def request(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        request_id: str,
        include_content: bool = False,
        cursor: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Authorized request composition + optional paged content (DEC-T16 / DEC-T13)."""
        self._require_thread(owner, agent_id, thread_id)
        size = max(1, min(int(limit), 100))
        inspection = RequestInspectionService(self._repos)
        snap = inspection.get(owner, agent_id, thread_id, request_id)
        components = list(snap.get("components") or [])
        reason_codes: list[str] = []
        if snap.get("components_truncated"):
            reason_codes.append("source_truncated")
        if snap.get("metadata_truncated"):
            reason_codes.append("source_truncated")

        summaries: list[dict[str, Any]] = []
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                continue
            component_id = str(
                component.get("component_id") or component.get("id") or f"{request_id}:{index}"
            )
            content = component.get("content")
            truncated = bool(
                component.get("truncated")
                or component.get("content_truncated")
                or snap.get("components_truncated")
            )
            summaries.append(
                {
                    "component_id": component_id,
                    "kind": component.get("kind"),
                    "order": component.get("order", index),
                    "role": component.get("role"),
                    "estimated_tokens": component.get("estimated_tokens"),
                    "content_hash": component.get("sha256") or component.get("content_hash"),
                    "truncated": truncated,
                    "redacted": bool(component.get("redacted")),
                    "missing": bool(component.get("missing")),
                    "injection_id": component.get("injection_id"),
                    "tool_call_id": component.get("tool_call_id"),
                    "source_ref": source_ref("request", f"{request_id}:{component_id}"),
                    "content_ref": source_ref("request", f"{request_id}:{component_id}:content"),
                    "has_retained_content": isinstance(content, str) and bool(content),
                }
            )

        start = max(0, int(cursor or 0))
        page = summaries[start : start + size]
        next_cursor = start + size if start + size < len(summaries) else None

        content_page: list[dict[str, Any]] = []
        if include_content:
            for summary in page:
                raw = next(
                    (
                        c
                        for i, c in enumerate(components)
                        if str(c.get("component_id") or c.get("id") or f"{request_id}:{i}")
                        == summary["component_id"]
                    ),
                    None,
                )
                body = raw.get("content") if isinstance(raw, dict) else None
                if not isinstance(body, str):
                    content_page.append(
                        {
                            **summary,
                            "content": None,
                            "missing": True,
                            "reason_codes": ["legacy_missing"],
                        }
                    )
                    continue
                content_page.append({**summary, "content": body})

        effective = self._effective_binding(owner, snap)
        turn_id = snap.get("turn_id")
        turn_steps = self._turn_steps(owner, agent_id, thread_id, turn_id, request_id)

        composition = dict(snap.get("estimated_tokens_by_kind") or {})
        if not composition:
            for component in components:
                if not isinstance(component, dict):
                    continue
                kind = str(component.get("kind") or "other")
                raw_tokens = component.get("estimated_tokens") or 0
                if isinstance(raw_tokens, bool):
                    continue
                if isinstance(raw_tokens, (int, float)):
                    composition[kind] = composition.get(kind, 0) + int(raw_tokens)
                elif isinstance(raw_tokens, str) and raw_tokens.strip().lstrip("-").isdigit():
                    composition[kind] = composition.get(kind, 0) + int(raw_tokens.strip())

        # DEC-T17: schema count ≠ token totals in composition.
        tool_schema_count = sum(
            1 for c in components if isinstance(c, dict) and c.get("kind") == "tool_schema"
        )

        coverage_level = "complete"
        if reason_codes or snap.get("status") in {"started", "pending"}:
            coverage_level = "partial"
        if snap.get("status") in {"failed", "cancelled"} and not components:
            coverage_level = "partial"
            reason_codes.append("capture_failed")

        return {
            "schema_version": SCHEMA_VERSION,
            "resolved_scope": resolved_scope(
                owner_user_id=owner, agent_id=agent_id, thread_id=thread_id
            ),
            "as_of": utc_rfc3339(),
            "request": {
                "request_id": snap.get("request_id"),
                "attempt_id": snap.get("attempt_id"),
                "turn_id": turn_id,
                "request_seq": snap.get("seq"),
                "run_id": snap.get("run_id"),
                "context_id": snap.get("context_id"),
                "status": snap.get("status"),
                "created_at": snap.get("created_at"),
                "ended_at": snap.get("ended_at"),
                "snapshot_phase": snap.get("snapshot_phase") or "model_visible",
                "model": snap.get("model"),
                "estimated_input_tokens": snap.get("estimated_input_tokens"),
                "actual_usage": snap.get("actual_usage"),
                "transformation": snap.get("transformation"),
                "composition": composition,
                "component_count": len(components),
                "component_counts": snap.get("component_counts") or {},
                "components_truncated": bool(snap.get("components_truncated")),
                "omitted_component_count": int(snap.get("omitted_component_count") or 0),
                "metadata_truncated": bool(snap.get("metadata_truncated")),
                "tool_schema_count": tool_schema_count,
            },
            "effective_binding": effective,
            "current_selection": self._execution_summary(owner, thread_id),
            "configured_defaults": None,
            "turn_steps": turn_steps,
            "components": content_page if include_content else page,
            "include_content": include_content,
            "next_cursor": next_cursor,
            "coverage": coverage_block(
                level=coverage_level,  # type: ignore[arg-type]
                reason_codes=list(dict.fromkeys(reason_codes)),
                next_cursor=next_cursor,
                source="request",
                quality="retained_inline" if include_content else "summary",
            ),
            "source_refs": [source_ref("request", request_id)],
        }

    async def trace_read(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        event_id: str,
        part: str = "all",
        cursor: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Page authorized args/result/injection from one trajectory event (DEC-T16)."""
        self._require_thread(owner, agent_id, thread_id)
        size = max(1, min(int(limit), 100))
        event = self._repos.trajectory_event_repo.get(event_id)
        if event is None or event.thread_id != thread_id:
            from octop.infra.errors import ErrorCode, OctopError

            raise OctopError(ErrorCode.NOT_FOUND, "trajectory event unavailable")

        payload = event.payload if isinstance(event.payload, dict) else {}
        wanted = (part or "all").strip().lower()
        chunks: list[dict[str, Any]] = []
        reason_codes: list[str] = []

        def _push(kind: str, key: str, value: Any) -> None:
            if wanted not in {"all", kind}:
                return
            text = _as_text(value)
            truncated = False
            if text is None and value is not None:
                reason_codes.append("legacy_missing")
                chunks.append(
                    {
                        "part": kind,
                        "key": key,
                        "content": None,
                        "missing": True,
                        "truncated": False,
                    }
                )
                return
            if text is None:
                return
            # Payload already clipped at persist time — disclose bound length.
            if key in {"args", "result", "content", "text"} and len(text) >= 64_000 - 1:
                truncated = True
                reason_codes.append("source_truncated")
            chunks.append(
                {
                    "part": kind,
                    "key": key,
                    "content": text,
                    "missing": False,
                    "truncated": truncated,
                    "content_ref": source_ref("trajectory", f"{event_id}:{kind}:{key}"),
                }
            )

        if event.kind == "tool" or "args" in payload or "result" in payload:
            _push("input", "args", payload.get("args"))
            _push("output", "result", payload.get("result"))
            status = _tool_status(event)
        else:
            status = None
            _push("input", "content", payload.get("content") or payload.get("text"))
            _push("output", "thinking", payload.get("thinking"))

        if event.kind in {"context", "system"} or wanted in {"all", "injection"}:
            injection = (
                payload.get("injection") if isinstance(payload.get("injection"), dict) else None
            )
            if injection:
                _push("injection", "body", injection.get("content") or injection.get("body"))
            elif wanted == "injection":
                reason_codes.append("legacy_missing")
                chunks.append(
                    {
                        "part": "injection",
                        "key": "body",
                        "content": None,
                        "missing": True,
                        "truncated": False,
                    }
                )
            elif event.kind in {"context", "system"}:
                _push("injection", "summary", event.summary)

        start = max(0, int(cursor or 0))
        # Character-budget page across chunk contents for long tool results.
        page: list[dict[str, Any]] = []
        budget = 8_000
        index = start
        while index < len(chunks) and len(page) < size:
            item = dict(chunks[index])
            body = item.get("content")
            if isinstance(body, str) and len(body) > budget:
                slice_end = min(len(body), budget)
                item["content"] = body[:slice_end]
                item["truncated"] = True if slice_end < len(body) else item.get("truncated")
                item["content_offset"] = 0
                item["content_length"] = len(body)
                if slice_end < len(body):
                    reason_codes.append("source_truncated")
            page.append(item)
            index += 1

        next_cursor = index if index < len(chunks) else None
        call_id = payload.get("call_id") or payload.get("tool_call_id")
        attempt_id = payload.get("attempt_id")
        return {
            "schema_version": SCHEMA_VERSION,
            "resolved_scope": resolved_scope(
                owner_user_id=owner, agent_id=agent_id, thread_id=thread_id
            ),
            "as_of": utc_rfc3339(),
            "event": {
                "event_id": event.event_id,
                "seq": event.seq,
                "ts": event.ts,
                "kind": event.kind,
                "mapped_kind": map_event_kind(event.kind, payload=payload),
                "summary": event.summary,
                "turn_id": event.turn_id,
                "request_seq": event.request_seq,
                "is_error": event.is_error,
                "status": status,
                "call_id": call_id,
                "attempt_id": attempt_id,
                "name": payload.get("name") or payload.get("tool"),
            },
            "parts": page,
            "next_cursor": next_cursor,
            "coverage": coverage_block(
                level="partial" if reason_codes else "complete",
                reason_codes=list(dict.fromkeys(reason_codes)),
                next_cursor=next_cursor,
                source="trajectory",
                quality="retained_clipped_payload",
            ),
            "source_refs": [source_ref("trajectory", event_id)],
        }

    async def _breakdown(self, agent_id: str, thread_id: str) -> dict[str, Any]:
        capacity_source = "compatibility_default"
        capacity_tokens: int | None = None
        compatibility = COMPATIBILITY_CAPACITY_TOKENS
        max_tokens = COMPATIBILITY_CAPACITY_TOKENS
        resolve = getattr(self._registry, "resolve_context_max_tokens", None)
        if callable(resolve):
            try:
                resolved = resolve(agent_id, fallback=COMPATIBILITY_CAPACITY_TOKENS)
                if resolved is not None:
                    max_tokens = int(resolved)
                    # Harness/registry resolved a value — still may be the compat default.
                    if max_tokens == COMPATIBILITY_CAPACITY_TOKENS:
                        capacity_source = "compatibility_default"
                        capacity_tokens = None
                    else:
                        capacity_source = "harness"
                        capacity_tokens = max_tokens
            except Exception:
                max_tokens = COMPATIBILITY_CAPACITY_TOKENS
                capacity_source = "compatibility_default"
                capacity_tokens = None
        resolve_capacity = getattr(self._registry, "resolve_context_capacity", None)
        if callable(resolve_capacity):
            resolved_capacity = resolve_capacity(agent_id, thread_id)
            if isinstance(resolved_capacity, tuple) and len(resolved_capacity) == 2:
                capacity_tokens, capacity_source = resolved_capacity
                max_tokens = capacity_tokens or compatibility
        result = await compute_context_breakdown(
            self._registry,
            agent_id=agent_id,
            thread_id=thread_id,
            max_tokens=max_tokens,
            usage_repo=getattr(self._repos, "usage_repo", None),
        )
        return {
            "max_tokens": capacity_tokens or result.max_tokens,
            "used_tokens": result.used_tokens,
            "capacity_tokens": capacity_tokens,
            "capacity_source": capacity_source,
            "compatibility_capacity_tokens": compatibility,
            "segments": [
                {"key": key, "tokens": result.segments.get(key, 0)}
                for key in SEGMENT_KEYS
                if result.segments.get(key, 0) > 0
            ],
        }

    def _meters(
        self,
        *,
        owner: int,
        agent_id: str,
        thread_id: str,
        breakdown: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Three named meter groups — never sum ledger + actual (DEC-T03)."""
        window = None
        if breakdown is not None:
            window = {
                "used_tokens": breakdown["used_tokens"],
                "capacity_tokens": breakdown.get("capacity_tokens"),
                "capacity_source": breakdown["capacity_source"],
                "compatibility_capacity_tokens": breakdown["compatibility_capacity_tokens"],
                "quality": "estimated_window",
                "source": "context_usage",
            }
        cumulative = None
        cumulative_quality = "unavailable"
        usage_repo = getattr(self._repos, "usage_repo", None)
        if usage_repo is not None and hasattr(usage_repo, "thread_totals"):
            try:
                totals = usage_repo.thread_totals(agent_id=agent_id, thread_id=thread_id)
                cumulative = {
                    "input_tokens": totals.get("input_tokens"),
                    "output_tokens": totals.get("output_tokens"),
                    "total_tokens": totals.get("total_tokens"),
                    "model_calls": totals.get("model_calls"),
                    "ledger_rows": totals.get("turns"),
                    "quality": "legacy_ledger_sum",
                    "note": "owner-scoped via service; not added to actual_usage",
                }
                cumulative_quality = "legacy_ledger_sum"
            except Exception:
                cumulative = None
                cumulative_quality = "unavailable"
        return {
            "window": window,
            "actual_usage": {
                "note": "per-request only; see context_request.actual_usage",
                "quality": "per_request",
            },
            "cumulative": cumulative,
            "cumulative_quality": cumulative_quality,
            "do_not_sum": ["window", "actual_usage", "cumulative"],
        }

    def _trajectory_coverage(self, thread_id: str) -> dict[str, Any]:
        repo = self._repos.trajectory_event_repo
        head_rows = repo.list_before(thread_id, before_seq=None, limit=1, kinds=None)
        observed_head = head_rows[-1].seq if head_rows else None
        # Earliest retained
        earliest = None
        try:
            for event in repo.iter_for_export(thread_id):
                earliest = event.seq
                break
        except Exception:
            earliest = None
        reason_codes: list[str] = []
        missing_ranges: list[dict[str, Any]] = []
        level: str = "unavailable"
        if observed_head is None:
            level = "unavailable"
            reason_codes.append("legacy_missing")
        else:
            level = "complete"
            if earliest is not None and earliest > 1:
                # Gap before first retained seq — may be legacy wipe or old prune.
                level = "partial"
                reason_codes.append("retention_gap")
                missing_ranges.append({"from_seq": 1, "to_seq": earliest - 1})
        revision = None
        if observed_head is not None:
            revision = hashlib.sha256(
                f"{thread_id}:{earliest}:{observed_head}".encode()
            ).hexdigest()[:16]
        return {
            "coverage": coverage_block(
                level=level,  # type: ignore[arg-type]
                observed_start=earliest,
                observed_head=observed_head,
                queried_range={"from_seq": earliest, "to_seq": observed_head},
                missing_ranges=missing_ranges,
                reason_codes=reason_codes,
                source="trajectory",
            ),
            "revision": revision,
        }

    def _count_model_requests(self, owner: int, agent_id: str, thread_id: str) -> int | None:
        try:
            rows = RequestSnapshotRepo_list(self._repos, owner, agent_id, thread_id)
            return len(rows)
        except Exception:
            return None

    def _tool_count_fields(self, events: list[Any]) -> dict[str, int | None]:
        call_ids: set[str] = set()
        attempt_ids: set[str] = set()
        schema_hint = 0
        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.kind == "tool":
                call_id = payload.get("call_id") or payload.get("tool_call_id") or event.event_id
                call_ids.add(str(call_id))
                attempt = payload.get("attempt_id")
                if attempt:
                    attempt_ids.add(str(attempt))
                else:
                    attempt_ids.add(f"{call_id}:1")
            if event.kind == "system" and payload.get("tool_schema_count") is not None:
                raw_schema = payload.get("tool_schema_count")
                if isinstance(raw_schema, (int, float)) and not isinstance(raw_schema, bool):
                    schema_hint = max(schema_hint, int(raw_schema))
                elif isinstance(raw_schema, str) and raw_schema.strip().isdigit():
                    schema_hint = max(schema_hint, int(raw_schema.strip()))
        return {
            "tool_schema_count": schema_hint if schema_hint else None,
            "logical_call_count": len(call_ids) if call_ids else 0,
            "attempt_count": len(attempt_ids) if attempt_ids else 0,
        }

    def _turn_steps(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        turn_id: Any,
        current_request_id: str,
    ) -> list[dict[str, Any]]:
        if not turn_id:
            return [
                {
                    "request_id": current_request_id,
                    "turn_id": None,
                    "note": "turn_id missing on snapshot",
                }
            ]
        try:
            rows = RequestSnapshotRepo_list(self._repos, owner, agent_id, thread_id)
        except Exception:
            return [{"request_id": current_request_id, "turn_id": turn_id}]
        steps = [
            {
                "request_id": row.get("request_id"),
                "seq": row.get("seq"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "model": row.get("model"),
                "estimated_input_tokens": row.get("estimated_input_tokens"),
            }
            for row in rows
            if row.get("turn_id") == turn_id
        ]
        steps.sort(key=lambda r: int(r.get("seq") or 0))
        if not steps:
            steps = [{"request_id": current_request_id, "turn_id": turn_id}]
        return steps

    def _effective_binding(self, owner: int, snap: dict[str, Any]) -> dict[str, Any]:
        context_id = snap.get("context_id")
        if not context_id:
            return {
                "context_id": None,
                "execution_context": None,
                "reason_codes": ["missing_execution_context"],
            }
        try:
            ec = ExecutionContextRepo(self._repos.db).get(owner, str(context_id))
        except Exception:
            ec = None
        if ec is None:
            return {
                "context_id": str(context_id),
                "execution_context": None,
                "reason_codes": ["missing_execution_context"],
                "source_ref": source_ref("execution_context", str(context_id)),
            }
        return {
            "context_id": str(context_id),
            "execution_context": ec.public(),
            "reason_codes": [],
            "source_ref": source_ref("execution_context", str(context_id)),
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
            # Fall back to repo selection when execution service absent.
            try:
                return ExecutionContextRepo(self._repos.db).selection(owner, thread_id)
            except Exception:
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


def RequestSnapshotRepo_list(
    repos: Any, owner: int, agent_id: str, thread_id: str
) -> list[dict[str, Any]]:
    inspection = RequestInspectionService(repos)
    # Page through retained requests (bounded).
    items: list[dict[str, Any]] = []
    before: int | None = None
    for _ in range(20):
        page = inspection.list(owner, agent_id, thread_id, before=before, limit=100)
        batch = page.get("requests") or []
        items.extend(batch)
        if not page.get("has_more"):
            break
        before = page.get("next_before")
        if before is None:
            break
    return items


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _tool_status(event: Any) -> str:
    payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
    raw = str(payload.get("status") or "").strip().lower()
    if raw in {"success", "failure", "cancelled", "pending", "unknown"}:
        return raw
    if getattr(event, "is_error", False):
        return "failure"
    if payload.get("result") is None and event.kind == "tool":
        return "pending" if raw in {"", "started", "running"} else "unknown"
    if event.kind == "tool":
        return "success" if payload.get("result") is not None else "unknown"
    return raw or "unknown"


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
