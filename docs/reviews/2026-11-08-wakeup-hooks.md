# Review, wakeup hooks and named background jobs, 2026-11-08

**Reviewed by**: independent review agent (author: root implementation agent)
**Scope**: uncommitted backend delta on release/1.0.2b23 against ab3daf01; spec 0050 including progress hooks.
**Verdict**: Approve

## Summary
The final reviewed candidate provides bounded arbitrary-JSON callbacks, named background jobs, durable completion intent and script-reported progress. All independently reported Major/Minor findings are resolved. No remaining concrete blocker or major was identified in the reviewed hook, delivery, origin-isolation, progress or policy paths.

## Resolution verification

- Hook transitions compare expected status and payload. Cancellation cannot be overwritten by a stale callback or scheduler snapshot; cancel during cron creation is covered by regression tests.
- Pending-hook selection considers queued hooks, expiry and terminal linked Jobs, avoiding starvation behind 128 long-running jobs. Waiting does not hold a model turn.
- Notification intent and labels persist in the original Job receipt and survive old-device observations. Reconciliation reconstructs a missing completion hook without resubmitting the accepted Job; temporary registration failure returns pending rather than turning successful submission into a false failure.
- Contextless callbacks return before current/saved-device selection and deny every runtime tool call. Context-bound feedback retains the original target and defaults to Ask mode through normal execution-context validation; explicit continuation is reviewed below.
- Cron claims queued/scheduled to running atomically after asynchronous preparation and before manager.stream. Cancellation after admission reports running honestly. Delivery exceptions finish the hook appropriately; boot recovery marks interrupted running deliveries unknown, which are not silently replayed.
- jobs.start validates the returned original expert/thread/target before writing title, notification or progress metadata. Same-origin idempotent replays preserve original intent. Cross-thread same-device receipt replays cannot rewrite the original Job.
- Progress association is reserved before dispatch using owner/expert/thread/target/idempotency identity. Reusing a hook for a conflicting submission is rejected before command dispatch; a genuine retry remains valid. Deferred binding can recover from a persisted receipt after restart.
- Progress records are independently labeled script_reported and do not override actual process status. Ordered mode rejects updates lacking sequence; stale sequence retries cannot replace newer progress. Missing percent remains absent rather than fabricating an estimate. Progress-only updates do not schedule cron/model work.
- Progress reads enrich the actual sidebar/background/job data from owner-bound persisted hooks; cross-owner queries return no progress.

## Strengths

- Only the exact callback POST path is exempt from JWT, and the credential is a distinct owner/hook HMAC capability.
- Authentication precedes body consumption; generic JSON and event names remain bounded and are presented as data rather than new instructions.
- Original-thread locks, persisted reminder delivery and execution-origin validation are reused rather than introducing another model-execution path.
- Race tests cover cancellation during awaited preparation, not merely serial status changes. Recovery tests use persisted receipts without depending on a browser or a model call.

## Test coverage

Independent final check:
`uv run pytest tests/unit/devices/test_wakeup_hooks.py -q` — **38 passed**.

Coverage includes arbitrary payloads, scoped credentials, expiry, status-aware cancellation races, pending-batch fairness, durable completion intent, progress reservation/order/readback, cross-thread origin isolation, contextless runtime denial, read-only original-context feedback and dispatch admission. The main agent's full make-all run is separate and was still in progress during review; this report does not claim its completion.

No product source/tests were edited by this reviewer. No deployment, live model request or production mutation was performed.

## Final extension review: explicit continuation after cdc29c79

**Verdict**: Approve. No additional concrete blocker or major was identified in this extension.

- resume_mode defaults to observe. Explicit continue requires both a bound execution context and wake delivery; contextless and progress-only registrations reject it.
- The original context's work mode and requested resume mode are stored in server-side hook metadata and its idempotency fingerprint. Reusing an idempotency key with changed mode fails instead of silently broadening authority. Callback JSON cannot override these settings.
- Continued delivery uses the persisted origin context and registered work mode. Ask/Plan origins retain their runtime constraints; other supported work modes use normal Craft conversation tooling while preserving their original workflow mode. Normal for_run/target checks reject a revoked source and do not switch to a later selected device.
- Device MCP defaults/denies derive from the original stored context's device ID. An explicit empty ID for local execution suppresses device fallback, and live connector resolution subsequently uses the prepared context. No new callback authority or public capability was added.
- Existing atomic dispatch, cancellation and uncertain-result behavior remains unchanged by the mode extension. Automatic Job completion notifications still default to observe.

Independent final check:
`uv run pytest tests/unit/devices/test_wakeup_hooks.py -q` — **43 passed**. Added cases cover Ask/Plan/Agentic/Debug origins, device A despite later binding B, revoked A rejection, contextless/progress continuation rejection and changed-mode idempotency conflict. No model call, product edit or deployment was performed by this reviewer.
