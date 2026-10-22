# Unified schedule management

Acceptance contract (2026-10-22):

- `/tasks` browses all current-user owned experts and conversations by default, including self-reminders. Filter by expert, task category and search. Shared experts and other users' jobs remain private.
- Every owned expert row exposes a task button, including experts with no tasks. Hover previews show counts, task names and next fire/state. Buttons open the expert's cross-conversation task panel. Lists show conversation titles when available.
- Blue one-off, purple recurring and neutral ended labels appear in schedule lists and details. Order: active one-offs by next fire, recurring by next inter-fire interval (shortest first), ended last. Event triggers follow timed repeats.
- Initially fetch five rows; each More action requests five additional rows. Scope/filter changes reset pagination; stale requests cannot overwrite the new scope. Execution records and conversation links retain actual job ownership.
- Existing ordinary-task edit controls remain available through the management tab; self-reminder capabilities stay read-only.
- View conversation closes the workbench and navigates to the actual execution thread. Its time window and result excerpt locate/highlight the corresponding message, loading older history when needed. Hide the redundant open-conversation shortcut when already viewing that conversation. Result actions share one aligned row.

Implementation uses the existing task page, schedule browser and server cron projection; no schema migration or new dependency.

UI polish: compact aligned controls; two-line task card titles; blue/purple/neutral task icons and labels; separate expert/conversation metadata; a distinct detail header; aligned result actions; responsive single-column list/detail navigation.

Verification:

- Full backend non-live suite: 5101 passed, 157 skipped (1195.48s). Follow-up API/permissions/i18n suite after incremental changes: 96 passed. Final listing/summary/i18n checks: 80 passed.
- Final frontend regression: 33 passed across schedule browser (including explicit mobile list/detail switching), expert shortcuts, workbench, sidebar, message positioning/history loading and matching.
- TypeScript project build, strict mypy (688 source files), repository Ruff lint/format and final Vite/PWA production build passed. These checks were run individually; the repository pre-commit gate is also required during integration.
- Isolated real Octop server and browser: initial 5 rows; explicit load more reaches 6 ordinary tasks and 9 reminders; computed labels are blue/purple/neutral. 390px viewport has no horizontal overflow. Mobile detail mode uses explicit responsive state to hide the list and expose Back; this final adjustment is covered by a component regression check.
- Browser snapshot/DOM/style checks completed. GPU screenshot capture was unavailable (surface timeout/black capture), so a pixel-level screenshot review is not claimed.
- Integration scope: commit and merge the task-panel changes only. No release tag, deployment or modification to an existing running profile.
