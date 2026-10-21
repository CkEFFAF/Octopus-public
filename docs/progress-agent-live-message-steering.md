# 0033 runtime message insertion — implementation progress

## 2026-10-21 combined release

The user explicitly authorized merging and deploying both unreleased revisions.
They are being published together from `hotfix/immediate-steering-and-receipts`.
The latest full regression remains5050passed157skipped; the normal pre-commit
gate is required before publication. A workspace GNU make4.4.1 is available when
run outside the Windows sandbox. Hub cutover must wait for idle, preserve device
and GPU work, and verify the exact merged source, built static and pinned Harness.
PR, CI and deployment completion are recorded separately in the release evidence.

## 2026-10-21 revision5: stale self-reminder receipts

The follow-up screenshots exposed an independent scheduled-delivery path that
consumed insertion events without updating receipts or broadcasting control frames.
Read-only production correlation proved one waiting receipt already had its exact
inserted human message in history; a second unknown receipt had no such proof.
No production task or database was mutated during diagnosis.

Implemented scheduled control observation, explicit terminal/active-idle updates,
canonical-message receipt repair, and a separate clear-status action that retains
audit data without replaying or cancelling work. Pending work cannot be dismissed.
The revision4 Harness artifact is unchanged. Final evidence: full non-live backend
5050passed157skipped36warnings (494.53s,exit0),156cron/queue/API tests and84UI tests
pass, Ruff/format and mypy pass, i18n76pass, TypeScript and production build pass.
Both revisions are uncommitted and not
deployed. Details: `docs/reviews/2026-10-21-stuck-steering-receipts.md`.

## 2026-10-21 revision4: immediate insertion

The user requested an additional action that interrupts a currently waiting tool
and inserts the queued message immediately, plus matching UI. Implemented against
the latest local application baseline `210529788395aa7ec953ea94cb7192582498beb9` in
`octopus-connectors-skills-repair-20261019`; the historical worktrees below were
not edited. Local code is uncommitted and has not been merged or deployed.

Both queue-row choices are present: insert after tools finish, or interrupt and
insert now. Immediate mode is bound to the authenticated run, persisted in its
receipt and applied once. Current tool handler waits are cancelled, each call gets
an interrupted ToolMessage, and the graph continues with the inserted input. A
backend ignoring cancellation does not block insertion or supply a second result.
The model/UI explicitly say external/background work may continue. Narrow-screen
queue rows place status below the message text to preserve room for all actions.

Verification: full non-live backend **5045 passed,158 skipped**; final installed
wheel queue/API/real-graph regression **27 passed**; original Harness steering
regression **10 passed**. Dashboard focus **26 passed** and broader chat-store/queue
**71 passed** (overlapping runs), TypeScript/build pass. Application Ruff/format
**1355 files**, mypy **672 files**; Harness Ruff/format **359 files**, mypy **194 files**.
i18n **76 passed**. GNU make is absent; its applicable commands were run directly.
The real component was clicked via ego-browser using synthetic callbacks; both
modes selected the expected queue item and375px layout had no horizontal overflow.
Screenshot capture was unavailable, so screenshots are not counted as evidence.
Temporary preview files, browser space and server were removed/stopped.

Final Harness `1.0.2.post4.dev4+interrupt.2` preserves all368unaffected runtime
members; the three changed modules, readable patch, exact wheel/source archive and
hash manifest are under `vendor/harness/`. All371installed runtime members match
the full-suite-tested code and final lock. Full details and remaining execution
limits: `docs/reviews/2026-10-21-immediate-steering.md`.

## Historical progress

Date: 2026-10-18 Asia/Shanghai. Spec: docs/specs/0033-agent-live-message-steering.md revision2.
Branches: feat/agent-live-message-steering in app and companion Harness.
App baseline 323f585; Harness baseline 6636ce2c4fed85c92f37da66459a218ddf158aef.
No feature commit, push, merge, production deployment, or public package release has been performed.

Implemented: durable FIFO queue, acknowledgement before draft clear, atomic queued withdrawal vs dispatch, retries by command identity, immutable execution/composer snapshots; per-run text steering before/during/after model and tool calls; model-only cancellation with partial text checkpointed and marked; stale planned tool suppression and already-running tools finishing once; ordinary and approval-resumed streams; same dashboard session lock for resumed operations; receipt persistence/broadcast and SSE/WS event deduplication; active receipts remain visible beyond recent history window; fair paged scan of per-thread heads; recovery never replays possibly-started work. Direct insertion inherits active settings; attachments and setting changes use queue. Bridge/team preserve their existing transport behavior.

Checks completed:
- Full app non-live suite: 4921 passed,157 skipped,37 warnings (ops/live-steering-app-final-tests.log and XML).
- Full Harness suite:1846 passed,31 skipped (ops/live-steering-harness-tests.log and XML).
- App mypy:661 files; Harness mypy:193 files; Ruff checks passed before final documentation edits.
- Dashboard typecheck passed after implementation; rerun status for final SSE ownership fix below.
- Latest pre-final Dashboard targeted regression:41 tests across6 files passed.
- Full Dashboard:1414 passed,12 failed. Same12 failures reproduced individually on untouched HEAD dashboard under identical dependencies (baseline25 passed,12 failed). Sources: sidebar permissions, control admin route expectations, RunReceiptBrowser labels, useChatDockPanel. Evidence ops/live-steering-dashboard-results.json and live-steering-dashboard-baseline-results.json.
- Local HTTP app: auth/scope/idempotency/withdraw/schema tests passed. Local browser observed native phase text and both Direct insert/Queue controls; applied insertion receipt and queued command persisted/completed. Preview is synthetic localhost only; production GPU manager chat untouched.
- History fixes were reproduced red first; 62 history/archive tests passed after fixing incremental-insert loss and original-human overwrite.
- Independent check reviewer found5 P2 issues; source fixes plus targeted tests cover raw OpenAI tool payload, fairness, active history visibility, resume lock and receipt updates. Reviewer then found old SSE completion clearing the next queued run. This final frontend fix and regression test are now written but runtime verification remains pending.

Final verification completed 2026-10-19 after the user's manual approval retry:
- Elevated frontend execution succeeded; the prior approval quota/esbuild blocker is cleared.
- Added2200-event delayed SSE cases (with and without a queued successor). The long-stream bug reproduced red, then all44 targeted tests across6 files passed after using exact per-stream sequence intervals and explicit predecessor/run ownership.
- TypeScript passed. ESLint and Prettier for the final changed stream files passed.
- Final production Dashboard build succeeded (50.08s), including PWA output. The packaged static output now matches the final source. ops/live-steering-frontend-final-build.log and live-steering-frontend-final-proof.json record the result and artifact hashes.
- Independent reviewer /root/premerge_review rechecked the final fix and found no remaining material finding.
- No feature merge or deployment was performed. The12 existing full-Dashboard failures remain separate baseline debt; do not report the entire Dashboard suite as green.

Next authorized release work, if resumed: preserve hooks, include both source repositories and the pinned wheel, and use GPT5.6 Luna medium for routine Git/cloud steps per user preference. Production GPU-manager chat must remain untouched by tests.

Packaging: app vendor/harness/octop_harness-1.0.2.post4.dev1-py3-none-any.whl, SHA256 2d89f428ebfc72f4f77bc674b4cc2382b11a15d31dff8d91ca3d2147b530d35f. 370 packaged files match companion source; installed agent/steering/protocol verified identical. uv.lock hash corrected and uv lock --check --offline passed. vendor/harness/.gitignore explicitly includes the required new wheel. source-manifest.json describes uncommitted source honestly. No public release.

Ops scripts: ops/live-steering-preview.py binds127.0.0.1:18033 only, fake local model, disposable homes. It created a disposable browser-only test login key. Do not publish preview logs/homes (contain synthetic auth material). Keep source repo fixtures isolated. Old unrelated admin pytest folders were not deleted.

Final frontend race fix is now applied in normal sandbox: SSE completion/error is bound to its own observed run and cannot clear the next queued run. Regression added; final TypeScript build passed. Vitest still cannot start esbuild in sandbox (spawn EPERM); final regression execution and new Dashboard production build remain pending. uv.lock wheel hash was checked against actual archive and corrected; uv lock --check --offline passed.

The disposable localhost preview process was stopped after verification. Final screenshot recapture was unavailable because local browser use was disabled in Work settings. No production service was changed.

2026-10-19 final result supersedes the earlier sandbox/approval-blocker notes below: testing and build were retried with manual authorization and completed successfully.

## UI integration and release follow-up — 2026-10-19

UI PR31 is merged at c02bf40745f41e201e9298176ebe3157d7cdd46b. This isolated worktree combines that source with0033, preserving task-results and sharing behavior. GPT-6 Luna reviewed the combined source and fixed two additional P2 boundaries: retire a known terminal steering receipt ID before a manual retry in a later run, and reject persistent inputs for team, Bridge and non-Dashboard threads at the shared REST/WS service boundary. Frontend4 and gateway10 targeted tests, Ruff and Prettier pass. An earlier GPT-6 fix removes an id-less empty tool-call tail with Overwrite; its targeted Harness test passes.

The integrated wheel is1.0.2.post4.dev1+taskresults.1, SHA256 beb8636d683391cb8dc6e22d5384e70c5f771f0be1ddf52c3ffbfb6ce6482e14. All370 manifest source entries and the wheel/lock/manifest hashes match; staged wheel bytes equal working-tree bytes. The independent review found no remaining blocking issue; complete integrated runtime gates are still pending. Historical gate results above apply to their earlier snapshots.

The latest user explicitly authorized merge and Hub deployment and specified GPT-5.6 Luna high for Git/operations and GPT-6 Luna for review/fixes. This supersedes the historical medium-effort handoff note. Deployment preflight confirms the old Hub remains healthy at bbc9a31 with Harness1.0.2.post3; backups are valid. Recheck active operations and an idle window before cutover; keep device service and GPU jobs running. No steering PR, merge or deployment has yet been completed at this checkpoint.

Final integrated gate: full non-live backend4952passed159skipped36warnings (exit0); targeted Vitest10files45tests passed (exit0); tsc, Vite production build, Ruff check/format and mypy passed. uv sync --frozen installed the final combined wheel. The45-path staged diff has no unresolved conflicts or whitespace errors and matches the working tree. These integrated results supersede the pending-gate notes above; normal-hook Git/PR publication and production cutover are the remaining release steps.

## Queue-first UI refinement — 2026-10-19 (spec revision3)

The user clarified that sending while an agent is running defaults to queue. Interrupt-and-insert and withdrawal belong to each already queued message, rather than three draft-composer actions. The composer now keeps its separate Stop control while typing and uses the queue icon for its running-turn send action. Each row has insert and withdraw/edit icons with status and unsupported/pending states. Draft text is untouched by promoting another message; withdrawing uses the existing overwrite confirmation and locks edits while its response is pending. Responses targeting a previous thread cannot overwrite the active thread.

Promotion is a single authenticated POST `/agents/{agent}/threads/{thread}/inputs/{command_id}/steer` with the original queue identity and a bound runtime ID. The server takes text from the saved queue snapshot, atomically reserves it against dispatch/withdraw, preserves snapshot and FIFO sequence, restores queued state on explicit rejection, and records uncertain outcomes without automatic replay. Attachments and slash commands stay queued. The Harness/wheel/lock are unchanged.

Evidence: targeted frontend five files38 tests passed (including queue-default behavior, selected-item routing, pending duplicate suppression, unsupported input, acknowledgement retries and delayed withdrawal draft protection); final TypeScript and production gates pending at this checkpoint. Backend queue/API target19 tests passed, Ruff passed. Root reviewed the backend CAS/restore paths. GPT-6 Luna reviewed the frontend, found the delayed-withdrawal draft overwrite window and root added pending locking plus regression; follow-up review pending. Actual ChatInput localhost preview with synthetic callbacks verified default queue, insert of the selected second item while preserving draft, overwrite-confirmation cancel and empty-draft withdrawal, and375px layout. This UI observation does not claim a real-provider or production-thread interruption test. Screenshot evidence is in root workspace `ops/steering-queue-first-ui-20261019-wide.jpg`; temporary preview files must not be committed.

Revision3 follow-up review found that a withdrawn attachment snapshot could be lost if its response returned after navigating to another conversation. A small agent/thread-keyed session recovery store now retains the entire snapshot (with memory fallback) and restores it only in the matching composer; current drafts remain protected while the withdrawal is pending. Attachment/context preview edits are also guarded. Frontend targeted five files39 tests pass, including delayed response after switching away and restoration upon return; final TypeScript/build are being rerun after the mount-lifecycle guard. GPT-5.6 Git worker hit a temporary usage limit (retry13:05 local); its already-running full backend test process remains intact and must not be duplicated.

Final revision3 integrated evidence: full backend4961 passed157 skipped36 warnings (exit0, existing session66489), Ruff check/format passed. Frontend five files40 tests passed, including rapid unmount/reopen before the delayed withdrawal response; keyed store subscriptions notify the active matching composer, protecting an existing draft via confirmation. The pending modal restore checks the captured agent/thread before applying. TypeScript previously passed and ESLint reports0 errors with2 existing hook-dependency warnings. A production build passed before the final subscription addition; the Git worker is rerunning final mypy (after an explicit str narrowing assertion), targeted backend regression and final production build. No backend behavior changed after the full suite. Temporary preview server stopped and its two files removed. No production thread was interrupted for verification. Final PR/merge/deploy still pending.

Final revision3 acceptance and review are now complete: GPT-6 Luna's final read-only review reports no remaining blocker after all mount/switch/subscription recovery paths were unified behind overwrite confirmation. Final frontend aggregate42 tests pass: latest five-file run had40 passing while two new real-Antd modal cases needed the selector/animation wait corrected; the corrected ChatInput file rerun is11/11 passing, with all other four files31/31 passing unchanged. Test stderr contains jsdom's existing unsupported pseudo-element getComputedStyle warning from Antd scroll locking; test exit is0. Final source tsc passed; ESLint0 errors2 pre-existing dependency warnings. Full backend4961passed157skipped36warnings and target19passed; final mypy662files and Ruff passed. Worker owns final production build and normal-hook hotfix publication. No source change is pending.
