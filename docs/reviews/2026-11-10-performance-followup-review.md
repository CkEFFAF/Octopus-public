# Review, feature/harness-performance, 2026-11-10

**Reviewed by**: gpt-6-astra (explicit reviewer override; author on Codex)
**Scope**: 44 files in the uncommitted diff against HEAD, base `f71eb815af01a7b32d0237968a8754d1387dd762`; emphasis on phase 2, with phase 1 findings retained in the separate harness-performance review. This report is excluded from the count.
**Verdict**: Approve

## Summary

The follow-up adds bounded process-local measurements, fair per-target Job observations and backoff, local manifest version reuse, complete-text-block digest reuse, incremental frontend grouping, and explicit HTTP MCP concurrency. No outstanding blocker, major, or minor was identified in the final inspected phase 2 changes. The new performance endpoint initially exposed an untyped OpenAPI response; the author corrected that during review. This verdict concerns code review and does not certify completion of the full backend suite or the repository ship gate.

## Resolved during review

### Typed performance response, `src/octop/api/routers/admin.py`

The initial `dict[str, Any]` return exposed an unspecified object in OpenAPI, contrary to AGENTS.md's requirement for readable API schemas. The author added `PerformanceResponse`, `DurationMetrics`, and `CacheMetrics`. Independent OpenAPI generation against this checkout confirmed the response reference and both nested schemas; validation also preserved unknown percentile values as null. No reviewer source edits were made.

### Admission lifecycle regression coverage, `tests/unit/agents/test_mcp_tool_cache.py`

The author added a regression test preserving active-call cancellation, queued-call cancellation, a limit reduction while old wrappers retain active leases, and subsequent capacity reuse. The reviewer independently exercised these transitions against the current `_InvocationGate` class loaded from the source AST. The checks passed, including retaining the reduced limit until the remaining old call releases its lease.

## Strengths

- Measurements use fixed names, finite nonnegative samples, a bounded 512-sample window, explicit unknown empty durations, and the existing admin permission dependency. Timing contexts preserve exceptions.
- Poll ordering ranks jobs within owner/target groups before the global limit. Per-target sequencing and bounded backoff leave observation capacity for other targets, while reauthorization continues to use the frozen execution context and never resubmits a job.
- Manifest reuse is restricted to exact local backend/workspace types, reopens the file for access checking, includes Windows ChangeTime, and falls back to rereading unsupported sources. Disabled skills and workspace changes remain live.
- History caching reuses serialization and hashes, not assumptions that database bodies still exist; insertion and reference bookkeeping remain transactional. Frontend ancestry retains numeric identities rather than old arrays and falls back to complete grouping when ancestry is unknown.
- MCP concurrency stays opt-in and HTTP-only. Admission is shared across wrapper versions, authorization runs after waiting, and a changed parallel policy rejects stale parallel wrappers. Test repairs retain assertions while using supported avatar data, temporary database paths, and actual dynamic-import readiness.

## Test coverage

Author-provided signals at review start: 25 backend and 8 frontend P0 tests; 36 metrics, 49 polling/hooks, 13 live-configuration, 31 MCP/custom, and 41 targeted grouping tests; full frontend 343 files/1,800 tests; mypy over 748 files. After the review fixes, the author confirmed 13 targeted tests including the typed endpoint and cancellation/reduction regression passed. These are author-reported results, not suites rerun by the reviewer. The full backend run was in progress and was neither duplicated nor interrupted.

Independent checks performed during this review:

- Transpiled the current TypeScript sources in memory and compared incremental grouping with full regrouping over 5,000 deterministic randomized snapshots. Inputs included role, speaker and wrap-up changes, multiple edits within a snapshot, skipped intermediate snapshots, and ancestry beyond the 16-hop limit. Every comparison passed.
- Loaded the current admission gate class from its AST and exercised queued cancellation, active cancellation, dynamic reduction from two leases to one, and subsequent reuse. All checks passed.
- Generated the final FastAPI OpenAPI schema with this checkout's `src` explicitly selected and validated nested metric response models and empty values. Passed. An initial probe without the explicit source path resolved an older editable checkout and was discarded.

The reviewed repository tests cover local manifest edits with restored mtime, deletion and recreation, remote/fake-workspace rereads, cache rotation/revocation, Job target fairness/backoff, history hash reuse with rewrites, immutable snapshots, metrics bounds, and endpoint authentication. No network, provider, GPU, live-device or PostgreSQL execution was performed; no wall-clock improvement or production throughput is claimed. The spec remains marked Assumed and architecture ratification remains recorded as owed; review does not change that status.
