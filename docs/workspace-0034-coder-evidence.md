# 0034 application coder evidence

2026-10-19, Asia/Shanghai. Working tree `feature/0034-workspace-annotations-activity`, base c236203c27c26d2f4beed5bec3aa9b437919dc41. No Git mutation or deployment performed by coder.

## Verification recorded

- `uv run --no-sync pytest tests/unit/agents/test_workbench.py -q`: 6 passed at queue admission fix. Covers durable queued/dispatching receipt, binding before or after HTTP acknowledgement, real immutable result publication, rejection of unadmitted/forged run, comments remaining open.
- Expanded cron/workbench/i18n/integration run: 231 passed. Includes actual APScheduler date fire, SQLite attempts, reminder exhaustion and no repeat on observation, pre-reset owner check, attempt recovery/history, bounded snapshot Range reads.
- `pytest` through uv for changed agent/db/backup/request-inspection contracts: 299 passed, 1 skipped after correcting fixed schema 30/31 expectations to actual new migration 32 and adding the public work_plan tool expectation.
- Focused actual local Job/reconciler/activity suite after bounded status wait: 17 passed. Real Python process is submitted through ExecutionService, independently reconciled with parent steering absent, and remains observed running. Old active records are independently queried outside the recent receipt history window.
- Execution target and i18n regression suite: 113 passed. Missing target is now EXECUTION_TARGET_REQUIRED (409); actual forbidden authority remains forbidden.
- Frontend targeted tests: 18 passed across TaskActivity (mouse delayed single click vs double click, keyboard summary), DocumentPreviewCore real SheetJS source coordinates/cross-sheet locate, nativeText and textFile. jsdom prints its known pseudo getComputedStyle diagnostic from Ant modal scrollbar measurement; tests passed.
- `mypy --strict src/octop`: success across 670 source files before final Harness integration.
- `tsc -b dashboard`: passed after workbench changes and native narrow directory drawer.
- Changed UI ESLint: zero errors, three hook warnings in existing DocumentPreviewCore/useChatDockPanel dependency arrays.
- Vite production build: succeeded, 9444 modules, 1m23s. Existing large-chunk and request.ts mixed static/dynamic import warnings; latest file UI edits require a final rebuild.

## Complete test runs

1. Full non-live, four xdist workers: 4952 passed, 158 skipped, 20 failed in 905.66s. Two tool-set assertions omitted new work_plan, eighteen migration/backup tests expected schema 30/31 rather than 32. Those exact affected modules were updated and passed the 299-test rerun above. This full run is not green.
2. Full2 non-live with activity.2: interrupted by root authorization at approximately 43% before dependency switch. No final outcome exists; no green claim. Ctrl-C ended session 86106, and a read-only Windows process query found no matching full2 pytest/xdist worker processes. The failed uv sync had only built/prepared packages and stopped at Windows locked octop.exe; metadata still reported activity.2. No dependency install may run concurrently with a full-suite run.
3. Final activity.3 integrated full gate: pending integration.

## Application changes in this continuation

Backend: AnnotationService.bind_run and manager queue binding; ResourceService authority-checked seek/read 64KiB streaming content; paired 032 cron_attempts migrations and repo; CronManager scheduler/timezone/session projection and exhaustion cleanup; actual CronDelivery attempt lifecycle with safe failure records, original/actual thread, real run; activity bounded recent history plus separate active query, explicit pagination and real dependency observation; missing-target domain error.

Frozen task UI sources for root review:
- dashboard/src/pages/Chat/components/TaskActivity.tsx, TaskActivity.module.less, TaskActivity.test.tsx
- dashboard/src/pages/Chat/components/TaskActivityGraph.tsx
- dashboard/src/components/ScheduleBrowser.tsx, ScheduleBrowser.module.less
- dashboard/src/pages/Control/CronJobs/index.tsx
- dashboard/src/api/modules/activity.ts, cronjob.ts; dashboard/src/api/types/cronjob.ts
- dashboard/src/pages/Chat/utils/publicMessageText.ts; CollaborationPanel.tsx
- dashboard/src/pages/Chat/index.tsx (mobile entry) and locale strings

Task UI now has three primary navigation entries, semantic current observation counts, list/graph filters, separate selected-node detail, native public messages, schedule list/detail and descending actual-attempt timeline, responsive return navigation and single/double click handling. These are code/test facts, not visual acceptance.

File UI still in progress under revision3: NativeDeviceFiles narrow tree drawer and compact toolbar are implemented/tsc checked. Batch annotations sidebar changed to 300px, can close/reopen, technical request IDs removed from first view. Selection-only annotation compose and final integrated responsive inspection remain to finish. DocumentPreviewCore retains actual original SheetJS cell addresses and restores cross-sheet selection; page/slide normalized rectangles are drawn on the selected page with a controlled location prop.

## Harness and runtime

activity.3 wheel approved by root: SHA256 9af63f12f5813ab490c7691e31bddfb2918c214ef509ea50eb851fe4d8f0e4a7. App vendor/pyproject/lock reference updated; Requires-Dist, Requires-Python and extras verified identical to activity.2. Frozen sync awaits release-owned backend stop because Windows locks octop.exe. The coder has not restarted the backend. No Harness source edits by this coder.

## Open acceptance

Root/user rejected initial visual layout. Revision3 replaces it; local CUA is currently disabled, so no fresh visual/layout pass is claimed. S1-S7 remain open until actual UI and runtime evidence closes each criterion. In particular App-level concurrent Harness dispatch/Job/DAG evidence, annotation request tool-produced result through an actual turn, remote files, large media seek and all responsive screenshots still need final verification. Backend-only, demo, installed subagent catalogs and scheduled definitions are never counted as running evidence.


## Revision3 UI freeze checkpoint

All task/schedule and file/annotation UI sources frozen by root instruction. Fingerprints: `docs/workspace-0034-ui-freeze-sha256.json`. `tsc -b dashboard` passed after the final source edits. Backend Ruff check and format check passed (1348 files).

NativeDeviceFiles now uses a narrow-screen left Drawer for directories and a 240px default desktop splitter tree. File toolbar/header spacing is compact. FileAnnotations is 300px, can close/reopen, and comment compose appears after a selected location or an explicit whole-file action. None of the 1390/894/375 visual or editor-line-height criteria is accepted without fresh real UI inspection. Root owns visual acceptance; independent review is reading the frozen sources.

The final dependency swap will happen only after release stops the locked backend. Full2 was stopped before installation; no final full-suite claim is made from that interrupted run.


## Explicit review corrections after first freeze

Root authorized spec9.8.2 corrections only. NodeDetail initial detail, older messages and Job logs now guard the selection/session epoch; React detail identity is keyed and current stale observation reaches its status. Public message text uses the existing public-only block filter and safe Markdown with localized role/time. Added a deferred old-response regression.

Plan cards now contain up to three actual contains-associated subagent/Job entries, active first and stable ID next. More shows exact task activity count and exposes every attempt, while only genuinely unassociated activity is in the separate group. Plan dependency arrows remain explicit. Geometry spacing changed to 280x220, without resetting scale on status changes. Added a real DOM selection/reachability regression. These three targeted test files passed 4 tests; the earlier final UI regression set passed 19 tests. The updated source fingerprints are in the freeze manifest.

The missing execution target view reuses DeviceTargetSelect and does not grant host/device access. New error enum/i18n and existing execution authorization regression suite passed 113 tests.

File annotation composer is now hidden until selecting a typed location or choosing an explicit whole-file comment. Its close/selection DOM regression passed. Visual review remains open.


Root additionally required conversation-scope protection for loadOlder. All result/error/busy writes now check the current conversation identity; a delayed A-history response after selecting B is discarded. The added DOM regression passed with NodeDetail/Graph/entry tests: 5 passed. `tsc -b dashboard` passed. Mouse repeated single/keyboard/touch summary opens are idempotent; Escape/outside pointer dismisses the summary. Updated source freeze hashes were regenerated after these authorized corrections.


## Harness activity.3 installed

After release stopped only the isolated backend tree, `uv sync --frozen --offline` completed with 2 uninstalled/2 installed: editable octop 1.0.2b16 and octop-harness 1.0.2.post4.dev3+activity.3. `importlib.metadata.version` and the `.venv/Lib/site-packages/octop_harness` import path were checked. Vendor SHA256 is 9af63f12f5813ab490c7691e31bddfb2918c214ef509ea50eb851fe4d8f0e4a7. Root and release_continue were notified; coder did not start backend.

A single integrated activity.3 non-live suite is now running via uv, xdist4, with evidence in `.0034-activity3-full.log` and `.0034-activity3-full.xml`. It has no final outcome yet. No further package install/sync will run during this gate.


Final pre-review code checks after activity.3 integration: strict mypy passed across 670 sources; production Vite build succeeded with its log at `.0034-final-vite.log`; TypeScript passed after the last authorized corrections. The activity.3 full suite is still running, and package/source mutation affecting that gate is paused pending its result. Read-only self-review flagged that actual Harness tool→Job identity association should be checked in S4; it must use explicit job/context/run identities, never task names or timing.


## 2026-10-19 23:18 — activity.3 full3 and revision3.3 corrections

Full3 ended normally: **4975 passed, 157 skipped, 21 warnings in 716.82s**. `.0034-activity3-full.xml` reports errors=0/failures=0/tests=5132/skipped=157. This gate covers the activity.3 integration and source BEFORE the following 9.8.3 corrections. No new full suite has been started.

Exact job_start producer association now requires a unique submission with identical owner/agent/thread/root-run/context/job identity. job_status/logs/cancel, ambiguous submissions and cross-context/run/thread references stay unlinked. Owner-scoped raw collaboration records verify source/scope/root identity before public ask_agent dispatches are canonicalized to the durable invocation. Dispatch task/attempt/source references and contains edges survive; status/public conversation remain collaboration-owned. Parallel task counts are recomputed after canonicalization. Accepted/waiting work contributes active counts but does not animate or claim running.

Upload resources with a legacy_path now re-read that alias before modification request creation/enqueue and compare SHA256 plus size. Actual repo/route tests prove changed and missing aliases return ANNOTATION_SOURCE_CONFLICT with no request and no queued call; unchanged aliases queue successfully. Authority checks remain unchanged.

ScheduleDetail pagination success/error/finally is guarded by selection epoch, including A→B→A identity cycles; poll error/finally also honor request epoch. Deferred response DOM tests cover old success, old failure, and an old finally not clearing the current selection's busy state. Accepted-only entry regression is green. TaskActivity/ScheduleBrowser/Graph targeted DOM tests: **8 passed**, log `.0034-983-vitest.log` (known jsdom pseudo-element getComputedStyle warning remains non-failing). TypeScript build passed. Strict mypy passed all **670** source files (`.0034-983-mypy.log`).

Root actual 375px inspection found the centered fullscreen modal wrapping below the viewport. The permitted fix disables centered under 650px, anchors a fixed inset-zero wrap, uses a border-box zero-margin/padding dialog and semantic Modal content radius instead of the wrong ant-prefix selector. Root is rechecking actual layout; coder does not claim visual acceptance.

User rejected the schedule detail right pane again. Root revision4 design is pending; no final UI freeze is claimed, and no further old-detail visual adjustments are being made. Existing TaskActivity navigation/graph/mobile corrections are preserved. Final build/fingerprint refresh awaits that approved detail implementation.


## Revision4 (spec9.9) implementation — awaiting actual visual acceptance

ScheduleBrowser detail is now result-first: a compact purpose header and schedule sentence, default execution-history tab with actual attempt status/time/public result, and a task-content tab. Reminder purpose comes only from safe meta.purpose, with the permitted self-check: name-prefix fallback; prompt templates are behind an explicit full-instruction disclosure. Ordinary task prompts remain available unchanged. Records have three-line public-result expansion, conversation links, and one grouped technical disclosure at the bottom. Date-ended presentation requires a real past date, no next run, recorded last-run terminal status, and actual server observed_at; missing registration of a recurring task remains unavailable. Exhausted reminders say ended, delivered says message sent, completed says execution finished.

Lists share the same purpose/state helpers, show one status and one time/result summary, and use a neutral selection border with a low-saturation background. Notification logic stays in the existing push hook: current visible thread still refreshes history/sidebar without opening a toast, while other/background pushes keep existing notifications. Tracked per-thread keys are cleared on route/visibility changes, never global notification destruction.

Actual mobile inspection found global layout.css [class*="-modal"] !important rules also matched wrap/content/body, adding margins, padding and max-width. The workbench now uses scoped semantic classNames and higher-specificity local overrides for zero margins/padding, full available width/height and independent content scrolling. Global modal styles are unchanged. Root must measure the real 375x812 dialog again; no CSS-only pass is claimed.

Final revision4 targeted UI regression: **13 passed across 4 files**, log `.0034-rev4-vitest.log`. This covers purpose/state, hidden internal instructions, more success/error/finally selection guards, active waiting entry, graph reachability, current-thread notification suppression, other-thread preservation and background-to-visible targeted cleanup. Relevant ScheduleBrowser/push source and test ESLint checks passed without errors or warnings. A prior final-source tsc passed; the final combined TypeScript/Vite build is in progress at this checkpoint.

Backend post9.8.3 final targeted gate is **47 passed**, `.0034-983-pytest.log`. The 4975-pass full3 remains explicitly pre9.8.3. UI sources are stable for root's live review; the final freeze manifest will be regenerated only after actual revision4 visual acceptance/corrections.


### Revision4 final live-review corrections

Root inspected the real 1390px page and accepted the new information hierarchy, then requested two scoped UX corrections before freeze: exhausted reminders no longer repeat fire counts in the schedule sentence (only actual last_run_at is shown there); task content and result excerpts only offer expand/collapse when their rendered clamped paragraph truly overflows. A ResizeObserver remeasures available size; text identity changes reset the disclosure, and expanded text retains its collapse action.

The latest focused UI set passed **14 tests across 4 files**, including measured short/long text and text-change regression (`.0034-rev4-vitest.log`). Relevant ESLint remains clean. The UI fingerprint manifest has been regenerated for the stable source, including the push hook and both locale files. Root's actual mobile measurement and final independent review remain separate gates. Final tsc/Vite rebuild is running after these last two small corrections.

Final revision4 live-review correction build completed: TypeScript and Vite production build exited 0; PWA generated 112 precache entries. Log: .0034-rev4-vite.log. The stable UI manifest matches current source; no UI source edits followed this gate.


### Final P2 date-lifecycle review correction

Root/reviewer identified that a failed or currently unavailable date schedule could be presented as ended. scheduleState now preserves any current scheduler state other than unregistered; for unregistered rows, actual last_status=error is shown as last execution failed. An ordinary date is ended only with no next trigger, a valid scheduled timestamp at/before server observed_at, last_status=ok, and actual last_run_at within [scheduled, observed_at]. Missing evidence, a run before the intended date, or a run after observed_at remains unavailable. Self-reminder exhausted semantics remain unchanged. Tab panels now reference unique per-detail tab IDs with aria-labelledby.

Focused regression after this correction: **14 passed / 4 files**, including the expanded date boundary assertions and tab label association. ScheduleBrowser source/tests ESLint passed. Source freeze hashes were regenerated; final TypeScript/build is running. Root separately reported real 375x812 measurement: dialog x=0/y=0/height=812, scrollWidth=375, no horizontal overflow, short purpose has no expansion control, full instruction hidden initially, return/close accessible. That evidence is root's actual inspection, not a coder visual claim.

Final P2 correction gate completed: TypeScript and Vite production build exited 0 (.0034-rev4-vite.log). Source freeze manifest is current; no further UI changes are in progress.


## 2026-10-20 S1 failure-state and S3 fixture replay follow-up

Root's live S1 directory view showed empty. Static review confirmed fs.list wire shape and executionApi unwrap agree; the actual device/API cause remains under runtime_restore investigation. One confirmed UI defect is fixed: initial/pending/failed reads cannot show a successful empty-directory state. NativeDeviceFiles now renders loading or a local translated error; only a successful entries=[] response shows empty. Refresh retries remain available. Listing request sequence plus context epoch rejects late results. No permissions or task/schedule UI were changed. Two DOM regressions passed (`.0034-s1-files-vitest.log`); relevant ESLint passed, final TypeScript exited 0 (`.0034-s1-files-tsc.log`). This is test evidence, not acceptance of the live directory listing. NativeDeviceFiles source fingerprint was updated independently of the frozen schedule UI.

Root explicitly assigned only ops/workspace-0034/scripted_openai_provider.py and its fixture test to this coder. Fixed nested request JSON decoding (JSONDecoder.raw_decode), title regex's missing source argument, OpenAI text-block content handling, exact approved-comment selection, required controlled SCRIPTED_S3_OUTPUT_PATH, real write_file file_path/content schema, and publish using the same absolute path and exact request ID. Incomplete resource text does not proceed. No App/runtime resource or request IDs were injected.

S3 offline replay is now **3 passed** (final `.0034-s3-provider-test.log`, 5.83s), fixture Ruff passed. The replay uses real SQLite AnnotationService nested comments/request text, QueuedInputBody/UserTurnWsFrame, an actual read_attachment tool result, the installed WriteFileSchema, a temporary local output, exact publish arguments, and stop-after-publish. Both string and text-block user content pass. Original source is unchanged and annotation status remains open. The earlier 2 failed/1 passed run was due solely to the test's wrong annotation state field and is superseded by this final green run, not counted as a pass. Runtime_restore was notified that provider may now be restarted with the root-approved controlled output path. Real S3 submit/run/publication acceptance remains open.

S4/S5 provider stage proposal has been sent to root for approval; no new stage or runtime mutations were made while awaiting that decision.


## Spec9.9.1 restricted-files protocol correction

Runtime_restore proved the actual S1 cause: restricted device rejects fs.list with HTTP403. Chat workspace now selects the existing restricted shared-root browser using files.*; owner/local stays on NativeDeviceFiles. ExecutionTarget includes actual optional roots metadata; absent restricted device metadata renders an explicit unavailable state without fake Device casts or access promotion.

RestrictedDeviceFiles now shares one typed files.* adapter: a supplied executionContext uses executionApi.call, standalone Devices page retains devicesApi.call. Listing/stat/read/write begin/chunk/commit/abort all use this adapter. Context scope hides cross-device transfer and ask/plan disables upload while backend context enforcement remains authoritative. Shared root_id/relative path are preserved. Context/device/mode/permission/root metadata switches remount scope and cancel old list/transfers; per-root/path request epochs discard late list writes, and old Blob URLs are revoked. Native loading/error/success distinction stays in place.

The slice supports existing restricted listing/upload/download only; it does not claim native editing/annotations for restricted devices. Shared rows use the same fileTreeIcon mapping. Native encoding tag/directory Drawer use local semantic classes instead of hard-coded ant prefixes.

Focused gate: **12 passed across 3 files** (`.0034-restricted-files-vitest.log`), covering restricted context protocol/ask-plan write disable/no transfer, standalone endpoint preservation, old context response cancellation, context upload/download/abort and Blob revocation, owner/local routing/missing metadata, native failed vs empty states. Relevant source/test ESLint passed. TypeScript and production build passed the adapter slice; final tiny icon/prefix checks are being finalized. Fingerprints/files are recorded in `docs/workspace-0034-restricted-files-freeze-sha256.json`. No root/browser visual acceptance is claimed: browser remains disabled. Schedule/detail UI sources were not changed.


### Restricted upload cancellation P2 correction

Reviewer reproduced a scope-remount leak: cleanup nulled the old controller and the catch guard returned before files.write_abort. The old captured adapter now attempts upload abort before checking whether its UI scope is current. A late successful write_begin records its upload_id before noticing cancellation, so that session is also cleaned up. New context state is never written by old catch/finally; an old context that is revoked may reject cleanup without bypass or false cleanup success.

Final focused files gate: **15 passed across 3 files**, `.0034-restricted-files-vitest.log`. Added deferred begin response, first-chunk-success/second-chunk-pending context switch, and revoked old-context cleanup failure regressions, all checking the original context/upload ID and no new-context write. TypeScript exited 0 and related ESLint passed. Restricted slice freeze manifest is regenerated. Production assets will be rebuilt for this final source.

S45 ops fixture (still gated, no real S45 launch) has an offline **8 passed** provider replay, including existing S3 tests. The stage emits a single assistant response containing two task calls (B/C) with distinct task/call/idempotency IDs, exposes streaming indexes0/1, waits for both exact public success receipts before D, and queries real Job identity/status/logs with bounded one-second intervals. Exhausted observation or failed process retains logs and reports not complete. Environment includes controlled sample paths/python/two actual subagent types and a unique run key; missing parameters or markers outside the current user turn cannot trigger it. Runtime capability confirmation remains required before use.

S45 provider final offline gate is now 9 passed (6.35s), .0034-s45-provider-test.log, with Ruff clean. Added failed parallel branch refusing join and missing join-result duplicate prevention. The existing S3 replay remains included and green. Runtime has been asked to prove the actual authorized target and two actual subagent types before supplying controlled env/trigger; no real S45 execution or UI pass is claimed.

Final restricted-files P2 source production build completed successfully (.0034-restricted-files-vite.log; 112 PWA precache entries). No source edits followed the frozen DeviceFiles hash 00475155e838ada48cddd836f7cf3ab47e6245a6093731b3ff0d03b1687b74e6.
