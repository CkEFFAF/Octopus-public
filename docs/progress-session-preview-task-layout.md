# Session preview and task layout refinement

Baseline: main `392a013a`. Requested by the user's 2026-10-23 screenshots.

Acceptance:
- Session titles retain their own line; time and activity controls use a separate line in both sidebar modes.
- All working-session shortcuts have the same white overview preview as recent sessions, including cached metadata outside the recent page. Hover never generates content.
- Preview shows a short topic, current progress and blocker/next step, with freshness. Old English prose in a Chinese account is identified instead of dumped into the preview. Stored/manual titles remain untouched.
- Expert background summary uses bounded cards and task counts, no raw IDs or full event stream in its default view. Detailed observations stay in a modal without navigating away.
- Schedule/reminder dialogs initially use the available width for cards, opening a detail view on selection with a clear back control; no empty detail column.

Implemented: shared SessionRowContent/SessionPreview in both sidebars and working shortcuts; owner-scoped cached preview data in sidebar-status; concise generation instructions; compact background cards with paged observation details; dialog-only schedule card layout.

Verification:
- `make all`: Ruff, strict mypy, 5,127 passed / 157 skipped.
- Related frontend interaction regressions: 30 passed across 5 files; TypeScript and production build passed.
- Real isolated app: other-expert working preview includes progress/next step, same conversation URL; titles occupy up to two lines with metadata below (measured 4px separation); background summary has 1 conversation / 3 tasks and no UUID dump; details show 8 of 35 observations and an explicit more button.
- Eight fictional reminders use two 388.6px card columns within a 787.2px list; selecting and returning from details preserves the current chat and leaves no empty detail column.
- Current account-selected OpenCode DeepSeek V4.1 Flash accepted a fictional request through the updated generation code: schema, Chinese objective, human stage and source refs passed. No real chat text sent or production conversation rows written.
- Browser screenshot capture timed out. DOM, computed layout and interactions were checked; no screenshot or 375px visual pass is claimed. One native pointer action required a DOM click after hit-testing confirmed the button was unobscured.
- Initial full-run failure was the new test patching a transient RepoBundle property; replaced it with a real persisted metadata fixture, then reran `make all` successfully.

Release: merge then deploy after normal commit hook and Linux CI. Windows checks waived by the user in this task history. Existing English summaries require explicit regeneration; hover performs no translation/model call and changes no stored title.
