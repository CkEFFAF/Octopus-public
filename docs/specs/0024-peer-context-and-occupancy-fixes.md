# Peer execution and context occupancy corrections

Status: Accepted

Requested: fix all four confirmed GPU chat issues from the 2026-10-17 review.

- AC1: Sync and inbox peer calls bind a real execution context to the callee,
  thread and run. Inherit retains the parent's target; member_default and explicit
  resolve their documented targets. Repeated preparation cannot reinstall parent
  identity. Account ownership, grant versions and Ask/Plan restrictions remain enforced.
- AC2: Context occupancy uses the thread-selected model (then expert/default
  resolution) and explicit runtime cap, with source provenance. A real 128000 cap
  remains known. Missing capacity remains unknown. Billing sums are never used as
  single-request occupancy. The ring refreshes after calls and model/thread changes,
  ignores late responses and does not turn connector filters into unknown capacity.
- AC3: Native expert creation/update accepts only a validated owned device/local
  binding. Omission preserves it, an empty object clears it, and receipts read back
  the saved target. This neither changes grants nor mutates in-flight runs.
- AC4: Nested peer token/reasoning/tool-call/usage streams do not become the parent
  answer. Child output remains in its own history and the parent's tool result.
  Each protocol stream/resume has an invocation boundary; real graph coverage is required.

No bulk rewrite of historical conversations or OS permission changes. Preserve
the already deployed memory maintenance capability. Verify with focused regressions,
normal repository gates and a frontend build; submit source changes for review.
