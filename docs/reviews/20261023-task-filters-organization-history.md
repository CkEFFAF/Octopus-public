# Task classification and organization history self-review

Baseline: main `2395fea5`. Acceptance is recorded in `docs/progress-task-filters-organization-history.md`.

- New background history projects only job identity, owned thread title, state and observation time; command/log payloads remain excluded. Status filtering and counts precede pagination. Shared/admin access never changes the effective owner.
- Organization browsing and batch insertion reuse one parameterized owner-scoped selection. Successful timestamps derive from existing ready jobs and generated briefs, while a new failed operation retains its own time. Digest/title suggestion jobs do not skew the overview refresh age.
- No database schema or provider/model configuration changes. Existing all-history behavior, manual title locks, active-batch reuse, idempotency and cancellation remain covered by regressions.
- Explicit time buckets are elapsed-time intervals with exact boundary tests. All failures are pageable independently of the legacy bounded diagnostic samples. Human-readable causes are shown in rows; source diagnostics remain behind Details.
- State and schedule type remain independent filters, including completed recurring reminders. Sidebar and detail views preserve the current chat URL. Detail filters inherit the inspected category. A shrinking active/failed page automatically returns to a valid page.
- Scoped async requests discard old results on filter/account component changes; refreshes avoid overlap. Both locale bundles contain the added labels; narrow layouts wrap the state controls. Hover previews are suppressed while the task modal is open.

This is a self-review, not an independent-model review. The final full rerun passed (5,131 tests / 157 skips); 34 interaction tests and TypeScript passed. Normal hook and final-head CI remain merge gates. Actual app evidence and screenshot limitations are in the progress record.
