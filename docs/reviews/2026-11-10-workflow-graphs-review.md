# Review, feature/workflow-graphs, 2026-11-10

**Reviewed by**: gpt-6-astra (independent reviewer; implementation by the main Codex agent)
**Scope**: 61 files, uncommitted Graph changes: unstaged diff plus untracked files. Staged performance changes are the baseline and excluded. The review artifact itself is excluded from the count.
**Verdict**: Approve

## Summary

The change adds owner-scoped configurable workflow graphs, immutable published versions, durable node execution, bounded branch state, explicit context policies, and a visual editor. Review against `AGENTS.md` and approved spec `docs/specs/0052-configurable-workflow-graphs.md` found several substantive execution, recovery, authority, and inspection defects; the author repaired them during review. The final focused source review has no remaining blocker, major, minor, or nit finding. This is code-review approval, not a claim that the ongoing full regression and real-browser verification gates have finished.

## Resolved during review

- **Routing and joins:** corrected condition comparison argument order; made nonterminal wait observation rotate beyond the oldest batch; aggregated failed join arrivals and emitted an error successor once. Failed merge groups reject a misleading single-arrival retry with actionable guidance, while an unknown, unarrived join retains its recovery path.
- **Capacity and recovery:** separated accepted-work reservations from activation status, preserving uncertain and superseded Jobs until terminal evidence; made reconciliation look up the original Job instead of submitting commands. Confirmed-dead local model workers release stranded reservations without replay. Preflight denials release unused slots, and the final dispatch callback checks the worker lease before submission.
- **Authority and execution source:** prevented Graph tools from bypassing Ask/Plan restrictions or shared-text scope; retained frozen execution/MCP origins; propagated script environment and frozen working directory; kept callback credentials out of ordinary inspection responses. Explicit owned-Job cancellation remains separate from run cancellation and now displays individual cancellation outcomes.
- **Receipts and signals:** rejected incomplete structured script output, handled permanent observation failures explicitly, and prevented one signal from completing multiple loop activations. The final `pending_wakeup_hooks` query excludes Graph signal hooks before applying its limit, so retained signals cannot starve ordinary wake deliveries.
- **Schedules and idempotency:** skipped missed scheduled occurrences on startup; advanced failed/deferred schedule cursors so unavailable origins cannot monopolize a batch; recorded blocked admission visibly; canonicalized nested object ordering for retry fingerprints; normalized invalid timezone errors.
- **Contracts and UI:** added typed inspection schemas with correct absent-context values, normalized imported definitions before rendering, and displayed a selected run's immutable version separately from its editable draft. Added page-level tests for publication revision, pinned-version inspection, normalized import, and stale selection, plus canvas authoring and read-only tests.
- **Migration compatibility:** the paired migration uses idempotent creation so existing schema-rebuild tests can recreate the database safely. The final incidental device-view test repair waits for the actual lazy-render prerequisite before settling imports.

## Strengths

- Transactional activation claims and transition commits, immutable versions, owner-qualified lookups, and explicit receipt evidence provide a sound basis for durable workflows.
- Branch-local snapshots and explicit join reduction keep parallel context and variable changes inspectable. Context projection preserves protected system content and tool-call/result pairing without mutating archived history.
- Recovery distinguishes observing existing work from authorizing a fresh attempt. Tests exercise real storage and a real local Job rather than relying exclusively on mocked state transitions.

## Test coverage

Focused author-run logs were inspected:

- `work/graph-runtime-tests-final.log`: **37 passed**.
- `work/graph-ui-tests-final.log`: **3 files, 12 tests passed**, including page orchestration, canvas interaction/read-only behavior, and example definitions.
- `work/graph-types-final.log`: strict mypy passed for **759 source files**.
- `work/graph-ui-types-final.log`: reported successful `tsc` execution with no output.
- `work/graph-backend-rerun.log`: **11 passed**, covering the failures from the initial broad backend run after the migration repair.

Independent reviewer probes confirmed:

- Ask/Plan mutating-tool and shared-text guards reject bypass attempts.
- A failing join merge consumes both arrivals and emits exactly one error-route successor; pending and finished activation inspection bodies validate against the typed response model. The functional assertions passed; that standalone probe's process exited with a Windows temporary SQLite cleanup error, which is not counted as a green test command.
- A script rejected by its frozen Ask execution context fails before dispatch and holds no capacity reservation; the probe exited successfully.
- Expiring a Script lease inside execution preflight prevents submission and releases the unused reservation; the probe exited successfully.
- With **130 queued Graph signal hooks** ahead of an ordinary queued wake hook, the bounded ordinary-wake query returns that wake hook; the probe exited successfully.

The author reported an initial full backend run of 5,642 passed / 157 skipped / 11 failed, followed by the successful focused failure rerun above. The author also reported an initial full frontend run of 1,797 passed / 3 failed, followed by successful profile/navigation and device-view rechecks. Those reports are not represented here as a final all-green full-suite run: broader regression gates and real-browser QA were still ongoing when this review was written. PostgreSQL execution, external providers/devices, and GPU workloads were not exercised by this reviewer. The final wake-hook query change received source inspection and the independent SQLite probe after the focused logs were produced.

## Focused follow-up review, 2026-11-10

**Reviewed by**: gpt-6-astra. **Scope**: 14 targeted source/test files covering the subsequent canvas/settings UI, normalization, runtime guards, signal query, and Agent-delivery fake/integration test. **Verdict**: Approve. The staged performance baseline and later documentation/examples were not reopened for broad review.

The full-screen route and flex layout remove the outer page wrapper. Workflow actions are collected in the settings Drawer; the library uses a separate Drawer, node creation is floating, the Inspector appears only for a selection, and run history is collapsible. Node presentation preserves accessible selection, connections and read-only run inspection. The page regression now checks that save/publish/start/import/export/undo/redo are inside settings rather than occupying the canvas header.

This follow-up found and closed one new substantive issue: advanced-node JSON normalization initially installed its captured whole-graph response after an asynchronous request, allowing a late result to overwrite subsequent edits or a different selected graph. The final implementation separates normalization from installation. `JsonField` invalidates request sequences on edits, changed serialized input and unmount; stale success and error results are ignored. Inspector installation additionally checks mounted state, graph object identity and selected node ID against the originating callback. Four focused tests cover canonical installation, intervening graph edits, unmount and stale validation errors. No unresolved finding remains from this follow-up.

The runtime changes preserve the intended boundaries: ready-node preflight errors claim an activation and consume its step budget before following error edges; lost authorization while observing an accepted Job retains an unknown outcome and its capacity reservation; model evidence is clipped by UTF-8 bytes; Graph tools recheck that the owner is active; and signal hooks are excluded before the ordinary-wakeup query limit. The fake harness appends messages through the canonical ID reducer, enabling a full server-delivery integration test that checks separate child history and a completed delivery receipt. Source and focused test review found no new substantive issue in these changes.

Validation for this follow-up: inspected `work/graph-ui-guard-final.log`, **4 files / 17 tests passed**, including the four normalization regressions and settings-consolidation test. The author reported **44 Graph unit tests and one Agent-delivery integration test passed**. The full backend run was still ongoing; this approval does not represent it as completed or green. No implementation, test or spec files were modified by the reviewer.

## Final gate evidence, 2026-11-10

**Final status: completed and green; review verdict remains Approve.** This paragraph supersedes the earlier chronological statements that full regression was still running. The reviewer inspected the final task-workspace logs: `work/graph-backend-final.log` records **5,666 passed, 157 skipped** in **1,078.75 seconds**; `work/graph-frontend-final.log` records **347 files / 1,817 tests passed** in **825.24 seconds**; `work/graph-focused-final.log` records **49 passed**, including the four subsequently added documentation examples. `work/graph-build-final.log` records a successful production build in **2 minutes 26 seconds**, and `work/graph-types-final.log` records strict mypy success for **759 source files**. The only reported subsequent source edit corrects a tool docstring from “get returns the schema” to “get returns the draft”; the corrected wording was checked and introduces no logic change.

The author's `docs/workflow-graphs-validation.md` records the complete validation scope. Real model inference, GPU workloads, external devices/providers, PostgreSQL execution, and dedicated mobile-browser verification were **not** performed. No deployment was performed. These limits remain unchanged by the successful local gates; the reviewer appended evidence only and did not modify implementation files.

## Execution-client compatibility follow-up

**Reviewed by**: gpt-6-astra. **Scope**: nine uncommitted files, limited to Job-environment capability advertisement, authorization/preflight, the fixed Graph error message, compatibility tests and guide text. **Verdict**: Approve; no unresolved finding in this increment.

Comparison with main `9adaf2fa` confirmed that old execution clients accept `jobs.start` parameters but omit `env` from the durable manifest and subprocess launch. Consequently, upgrading only the controller could silently lose Graph input, configured environment and callback variables. The new guard requires `job_environment_protocol_version: 1` for remote Jobs carrying nonempty environment variables. ExecutionService checks before `on_dispatch`; DeviceService also checks direct authorization. Local execution and legacy Jobs without environment variables retain their existing behavior. The Graph error path exposes only the fixed upgrade message, without reflecting environment values or callback credentials.

The reviewer independently reproduced a flaw in the first guard: a supported client's persisted capability survived an older client's reconnect, allowing authorization before the new connection acknowledged its capabilities. The final implementation closes this window by defaulting each `DeviceConnection` to unsupported and enabling the capability only after that current connection's validated `policy_applied` message. Persisted metadata remains informational for this capability. The added regression checks both preflight and direct authorization before acknowledgment, and rejection after an old-client acknowledgment. The supported-client subprocess test now asserts the actual `completed` terminal receipt and the complete environment contents.

Inspected `work/graph-client-compat-final.log`: **90 passed, two warnings, 33.98 seconds**. The author reported Linux strict mypy passing for 759 files; Windows strict mypy and the new CI run were still pending at this review checkpoint. Earlier full-suite results above predate this compatibility increment and are not represented as a rerun of it. The service had not been switched to this candidate; packaging/tree verification and deployment remain the author's separate release gates. The reviewer made no implementation changes, dispatched no command to a connected execution device, and performed no deployment.
