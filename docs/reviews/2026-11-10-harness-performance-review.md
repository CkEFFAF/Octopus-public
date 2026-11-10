# Review, feature/harness-performance, 2026-11-10

**Reviewed by**: Independent Codex review agent (model identity not exposed; author on Codex)
**Scope**: 20 files, uncommitted, base `f71eb815af01a7b32d0237968a8754d1387dd762`; temporary Vitest/Vite loader configuration excluded
**Verdict**: Approve

## Summary

The change reduces archive write frequency, batches history body reads, avoids redundant device observation writes and policy application, reuses connector schemas while resolving live authorization, and reduces frontend history copying. Two cancellation hangs were reproduced during review and corrected by the author before review completion. No outstanding actionable regression was identified in the final inspected diff; this is a code review verdict, not a claim that the still-running full regression suites have passed.

## Resolved during review

### Major: Source cancellation could leave the archive consumer waiting forever

**Location**: `src/octop/infra/history/stream_buffer.py:48` and `:73` in the final revised file (the original producer caught only `Exception`).

**Problem and evidence**: Reproduced independently using the implementation loaded from its source via Python AST, removing only the runtime import used for its deferred type annotation. A source yielded one token and then raised `asyncio.CancelledError`. The first `anext` returned the token, but the second remained at `queue.get` until an explicit 0.2-second `wait_for` timeout. `CancelledError` escaped the producer without enqueuing a terminal item, and the consumer did not observe producer completion. Consequently an internally cancelled source could leave a turn and its final history bookkeeping unfinished. This was a helper-level reproduction, not an end-to-end provider failure; the bundled harness's normal stop command uses an Event and returns, so the finding does not establish that ordinary Stop always hangs.

**Resolution**: The final producer retains `BaseException` as shared terminal state and closes the source before marking `finished` and setting an availability Event. The consumer drains already queued data before propagating terminal state. Independent repeat execution passed source cancellation propagation; regression coverage was added by the author. No reviewer code edits were made.

### Major: External producer cancellation could block shutdown behind a full queue

**Location**: `src/octop/infra/history/stream_buffer.py:57` in the final revised file; the intermediate implementation blocked at its line 58 (`await queue.put((terminal, None))`).

**Problem and evidence**: The author identified a remaining shutdown edge case in the first cancellation fix and requested independent verification. Reproduced independently with the source loaded via AST: after consuming the first token, the consumer was paused and the queue held 64 items. Directly cancelling the producer ran the source's `finally`, but the producer stayed pending at the terminal queue insertion after a 0.2-second observation window. Explicitly closing the consumer recovered it. Thus a shutdown path that cancels and awaits tasks before closing paused async generators could hang; this is an inference about Runner shutdown based on the reproduced pending producer, not a reproduction of a live server shutdown.

**Resolution**: Terminal state now uses shared `terminal`/`finished` variables and an Event; only data occupies queue slots. The final implementation has no await between detecting an empty unfinished queue and clearing/waiting on the Event, so the single-event-loop consumer does not introduce a lost-wakeup window. Independent execution against the final source passed all four checks: external producer cancellation completes with the queue full; all 65 already queued/forwarded fragments are drained exactly before propagating cancellation; source cancellation and consumer `aclose` with a full queue terminate cleanly; and a control barrier resumes into normal termination. The author added a regression test that first failed against the intermediate implementation.

## Strengths

- Archive coalescing preserves speaker and other metadata boundaries, bypasses legacy tracking, and treats control frames as barriers. The first frame remains individually forwarded. Persistence remains before forwarding in the existing processor/projector consumers.
- Frontend copy on write checks the published array identity and replaces message objects. Imperative snapshot reads refresh the snapshot before subsequent writes, preserving the immutable snapshot contract while eliminating repeated long-array copying within an unread burst.
- Connector reuse remains scoped to the middleware and credential fingerprint. Current visibility, selection, credential refresh and disabled-tool filtering still run at the existing model/tool boundaries. Skill files are reread; bounded metadata caching does not replace external-edit detection.
- Bulk history decoding batches SQL bindings and independently deserializes each reference. The new test checks independent mutability and missing-body failures instead of only counting queries.
- Job observations retain authorization before their journal-free path. Mutation journaling remains intact, unchanged heartbeat grants are skipped only after a successful application, and independent wakeup dispatch shares an overlap guard.

## Test coverage and limits

Reviewed the new and changed Python and frontend tests, including the untracked archive-buffer and device-observation tests. The author reported 138 targeted Python tests, 310 chat TypeScript tests, mypy and TypeScript compilation passing at review start; those are author-provided results, not independently rerun suite results. Full suites were already running and were not interrupted or duplicated. Independent execution was limited to the cancellation, full-queue shutdown, queued-fragment preservation, and control-barrier reproductions described above. No network, provider call, live device, browser session, or end-to-end durability fault injection was performed, and no wall-clock performance claim is made. The review examined ordering, cancellation and lifecycle paths, copy-on-write ownership, live credential/schema behavior, read-only operation semantics, decoding, and wakeup scheduling; it does not certify every runtime integration.
