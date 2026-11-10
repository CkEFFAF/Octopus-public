# Performance follow-up

**Status**: Assumed
**Authorized by**: User, 2026-11-10, “一步步完成”, following the ordered remaining-work list.

## Owed decision

Internal measurement and cache/scheduling details are recorded here before implementation. Research goal orchestration will have its own design using the existing task board and wake hooks.

## Assumption built on

Retain the existing stack, execution contexts, live authorization, durable-before-forward history, and immutable UI snapshots. No external services or dependency changes. These internal choices implement the user-approved optimization directions.

## Requirements and named inputs

1. Repair test assumptions without weakening assertions: supported avatars come from the existing catalog, database paths from pytest temporary storage, and Markdown readiness from completion of actual dynamic imports.
2. Performance measurements use `time.perf_counter`, fixed metric names, and at most 512 recent duration samples per name. Percentiles describe those samples, not historical population percentiles. Counters contain no owner, thread, URL, path, token, or prompt labels. Existing `/admin/metrics` is unchanged; `/admin/performance` uses the same `admin_console` permission. Empty measurements report unknown durations. State is process-local and resets on restart.
3. Instrument archive flush, MCP preparation, tool lock waiting and execution, first text arrival after stream entry, skill refresh, job observation and event-loop lag. Cache hit/miss counters cover the schema/manifest caches. Errors and cancellation retain their existing behavior.
4. Fair polling retains the global concurrency bound of four and original frozen execution contexts. Offline targets use bounded retry backoff; one offline target must not consume all observation capacity. Observation failure never resubmits a Job or changes its destination.
5. Manifest reuse is valid only when the workspace can provide an unchanged content version. Unsupported metadata falls back to a fresh read. Authorization remains live and invalidation covers edits, deletion, changed source and credential/account state.
6. Archive optimization reuses only unchanged complete text blocks. Rewrites, metadata changes and missing bodies preserve existing archive semantics. No reduction of SQLite durability.
7. Frontend grouping reuses the unchanged prefix and recomputes the changed suffix. Prepend, edit, speaker changes and wrap-up boundaries preserve grouping semantics.
8. MCP concurrency requires an explicit safe transport/capability contract, retains sequential defaults, and preserves cancellation, access checks and session lifetime.

## Code area

`infra/metrics.py`, admin router, history recorder/store, execution reconciliation, live configuration, MCP wrappers, Chat grouping, and their existing tests.

## Build plan

- [x] Repair remaining test failures and run surrounding tests.
- [x] Add bounded performance measurements and authorized inspection.
- [x] Add fair device polling and bounded backoff.
- [x] Add version-based manifest reuse with fresh-read fallback.
- [x] Reduce repeated archive encoding of unchanged text.
- [x] Incrementally group frontend messages.
- [x] Implement explicit safe MCP concurrency.
- [x] Verify the combined change and independent review.

## Ratify

The assumptions are recorded by develop. Architecture ratification remains owed for new behavior; this flag does not conceal the distinction between measured improvement and a proposed mechanism.
