# UI feedback and draft protection — pre-merge check

Baseline: `bc426e4556f9a3881ebdbf8c80a05efda9543a7f` (`main`). Contract: [0037](../specs/0037-ui-feedback-and-draft-protection.md).

The user explicitly requested continued optimization, merge and deployment, while retaining the original visual style. The implementation is isolated from the unmerged provider catalogue branches. This is a same-author review and real-app verification, not an independent second-model review.

## Findings addressed

- Provider changes can invalidate an in-flight connection test. Test results now carry the component's configuration generation; results from an older generation are discarded. A deferred-response regression verifies that the new configuration is not marked as tested.
- The fixed update banner has a higher stacking level than ordinary modals. The confirmation now appears above it, and update/dismiss actions remain disabled until confirmation completes or is canceled. Tests cover cancellation and restart-before-refresh ordering.
- AI task instructions were outside the form's change callbacks. They now participate in dirty state, including closing confirmation and the native browser unload guard.
- Polling cleared action failures. Task action failures now have separate persistent state; project save errors stay in the editor. Loading failure remains distinguishable from an empty dataset.
- Clearing task filters and switching projects previously replaced unrelated query parameters. Changes now update only the relevant parameters.

No unresolved blocking finding was identified in these changed paths. No backend API, permission, dependency pin, database migration or automatic model test is introduced.

## Verification

Targeted tests cover draft warning cleanup, task creation context, no-match recovery, duplicate model IDs, configuration changes during a test, historical error recovery and PWA confirmation. Real isolated FastAPI/SQLite verification confirms project-to-task navigation, AI and project input preservation, and browser unload prevention. The original palette, global theme and page shell remain unchanged.

Full local gates and PR checks are recorded in the task's deployment record after completion. Screenshot capture is unavailable in the browser environment; real-app evidence uses rendered structure, interaction and DOM geometry. SPA-wide route blocking, persistent drafts, global active-task update locking and physical mobile keyboard behavior are outside this batch.

Local full results: `make all PYTEST_JOBS=6` passed (Ruff; mypy 692 files; 5,132 passed / 158 skipped). Frontend full suite passed 1,601 tests in 296 files. Final update-confirmation changes were followed by 6 passing focused tests. A normal pre-commit hook will repeat its configured checks and generate the deployment build.
