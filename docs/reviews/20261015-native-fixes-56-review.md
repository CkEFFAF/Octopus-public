# Native execution fixes — independent incremental review

Date: 2026-10-15
Reviewer: gpt-5.6-sol, high reasoning; separate from the gpt-6.1-sol high implementation context.
Contract: spec 0015 revision 3; dirty architecture based on main `28a97280`.
Scope: the four Major findings in [native execution review](20261015-native-execution-review.md) and neighboring regressions. This record transcribes the returned independent review; it is not fleet acceptance or release approval.

## Verdict

No actionable findings in the inspected incremental scope. All four earlier Major findings are resolved:

1. Queued browser operations are rejected, and browser results are excluded from durable operation ledgers.
2. Immediate device browser calls require a persisted context, revalidate mode/policy, derive the lane server side, and verify the target device. The local backend applies the corresponding persisted context checks and lane derivation.
3. Execution tab identity includes the original expert/thread scope, retaining old frozen tabs without selecting them for another thread.
4. Recovery cancellation requires positive coverage and stop confirmation for every persisted process identity and worker. AccessDenied or incomplete coverage remains unknown; absent or reused identities count as stopped only after checking identity.

## Independent evidence

- 52 affected backend tests passed.
- 9 execution dock Vitest tests passed.
- Ruff passed for the four affected backend modules and three backend test files.
- Source tracing covered raw API, context API, model tool, device/local backends, durable operation ledger and RunEvent summary paths.

The reviewer changed no source, Git state, production device or permission. The subsequently added session-directory and immediate selection-persistence UI was outside this review and requires its own focused verification.
