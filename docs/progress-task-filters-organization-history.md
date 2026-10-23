# Task state filters and conversation organization history

Baseline: main `2395fea5`. User screenshots on 2026-10-23.

Acceptance:
- Background jobs and run details default to active observations. Completed and failed work have explicit filters; canceled/stale observations are under stopped/unconfirmed. Counts remain visible without dumping historical rows. Details inherit the selected category.
- Schedule and reminder browsers default to active work (running, scheduled or waiting for an event). Completed, paused/unavailable and failed entries can be inspected explicitly. Filtering occurs before pagination, including standalone browsing.
- Conversation organization has a paginated per-conversation list with expert/name, latest result, last successful organization, last attempt and readable failure reason plus diagnostics. No twenty-failure sample cap on the actual list.
- Age buckets: never successfully organized, under 1 day, 1–3, 3–5, 5–7 and at least 7 days since last success. Failed attempts do not advance the success timestamp. Labels make this interpretation explicit.
- Preview and execution use identical owner-scoped server filters; users can organize the filtered set or retry a specific conversation. Preserve all-history default, idempotency, active-batch reuse, cancellation and manual titles.
- Existing successful job timestamps and generated-at values supply history; existing durable jobs retain attempt timestamps. No schema migration is required.

Implement → targeted API/repository and interaction regressions → real isolated app verification → make all and build → normal hook → merge and deploy. Windows checks remain waived by the user's earlier instruction. Do not change provider/model choices or reprocess real conversations during verification.

Verification evidence before release:
- Repository/API regressions: 38 passed, including 25 failed conversations across pages, exact 1/3/5/7-day boundaries, ownership, atomic filtered enqueue and task classification. The final recurring-type + completed-state combination also passed the cron suite (5 tests).
- Final `make all` rerun passed (5,131 passed / 157 skipped; Ruff and strict mypy), including the type/state filter adjustment.
- Final frontend interaction suite: 34 passed; TypeScript passed. Normal commit hook and final-head CI remain release gates.
- Real isolated app: 2 conversations at least 7 days old, narrowed to 1 latest failure. Confirmation showed the actual filters. One controlled model call processed only that fictional conversation; ready=1, failures=0; successful time advanced while the other old conversation stayed unchanged. Batch start/end times displayed.
- Task panel: initial 1 active background job; completed explicitly selected 4 older jobs. Reminders initially displayed 1 upcoming item and excluded 8 completed items; selecting Completed exposed those cards. Schedules initially displayed only 1 upcoming item and kept the paused item in its category.
- Modal opening suppresses its hover preview; no tooltip covered the dialog. Pagination returns to a valid page when retries reduce the failed total.
- Browser screenshot API timed out again. DOM/interaction/state and isolated DB ledger verified; no screenshot or 375px visual acceptance is claimed. Ego Lite reported an available update after the space closed; no upgrade performed.

Release execution and final CI results are recorded in the PR and deployment manifest, after the gates above complete.
