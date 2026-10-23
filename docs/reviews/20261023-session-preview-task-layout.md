# Session preview and task layout self-review

Reviewed against `docs/progress-session-preview-task-layout.md`, baseline `392a013a`.

- All classic/minimal session entries now use the same title, metadata row and white preview. Older working shortcuts receive the same account/expert-scoped cached brief fields, without history reads or model calls on hover.
- Added preview fields are projections of existing brief data; no migration or permission expansion. API still filters owned conversations before projecting metadata. Regression uses real repository storage and retains foreign/deleted-thread cases.
- Display normalization does not mutate persisted/manual titles. English prose and stage identifiers are suppressed in Chinese previews, with an explicit update hint.
- Background default view omits job IDs and tool streams. Details are fetched only when requested, paged eight at a time, with raw source details behind item selection. No URL navigation is performed.
- Compact schedule layout is opt-in only for sidebar dialogs. Existing standalone desktop/mobile browsing and permission gates remain covered by the related regression suite.
- Async observation requests ignore stale results after scope/unmount; both locale bundles contain the added labels. Working expert avatar/status remains, duplicate working text removed.

Evidence: complete checks and real-app observations in the linked progress record. This is a self-review, not an independent-model review. No unresolved correctness finding; visual screenshot capture remains unavailable.
