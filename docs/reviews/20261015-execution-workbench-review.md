# Execution workbench incremental review, 2026-10-15

**Reviewer**: independent Codex reviewer, not the implementation author.

**Scope**: spec 0015 revision 3, previous four findings plus WorkMode stages, SDK evidence classification, asynchronous peer receipts, repository compare and swap, and WorkflowReceipt. Supplied baselines are main repository `28a97280` and SDK `1774fe9`. No Git operations were performed.

**Verdict**: Approve for the three requested corrections. The previous four findings and the three WorkMode findings below are resolved in the inspected implementation. No unresolved finding remains within this followup scope. This is an incremental review, not final release approval.

## Followup verification of the three WorkMode corrections

The followup was limited to these three findings and their direct regressions. The browser implementation and other unfinished work were not reviewed.

| Finding | Resolution verified |
| --- | --- |
| Semantic tool failures counted as successful evidence | `RunEventCallback` now interprets the known tool error contracts, classifies failed fetches and missing experts as failed, and removes source URLs from failed receipts. The interpretation is restricted to known tools, so reading a file containing error shaped text remains successful. Background dispatch submission remains accepted. |
| Child completion published too late for parent integration | The public inbox result observer publishes the child outcome before parent integration. Its `result_status` guard publishes once. `PeerTaskTracker` saves the dispatch outcome through this observer; its later delivery finish handler no longer rewrites that receipt. The parent can consume the completed receipt during its followup, and failed parent delivery leaves the successful child receipt intact. |
| Cowork completion bypasses user handoff | Completion validation now rejects every model completion of Cowork handoff, including before any decision artifact exists. The authenticated decision path still completes the handoff, with account and version checks. |

**Independent execution**: Ran six targeted cases directly from the current regression functions, using the current SDK source and in memory SQLite instead of filesystem temporary databases: actual failed localhost fetch plus nonexistent expert, error shaped file content, accepted background dispatch and successful source handling, Cowork decision transitions, and the real inbox plus database plus WorkMode integration with successful and failed parent delivery. All six completed successfully. The database substitution avoids the previously recorded Windows temporary directory ACL problem; it does not replace inbox, repository, callback or WorkMode logic.

Also inspected `.cache/review-fixes-regression.log`, which records `21 passed in 3.18s`. That is supplied pytest evidence, separate from the six independently executed cases above. No application code, Git state, browser implementation or production device was changed by this followup.

## Resolved Major findings from the initial WorkMode review

The descriptions below preserve the original failure conditions and reproduction evidence. They describe the implementation before the corrections verified above and are no longer outstanding findings.

### 1. Failed tool results can satisfy real execution evidence requirements

**Location**: `D:/Agent_Workspace/octopus/octop-harness-execution/src/octop_harness/observability/run_events.py:126`, also lines 133 through 149.

The callback considers every result without `ToolMessage.status == error` completed. Existing tools also return ordinary successful ToolMessages containing error values. `web_fetch` explicitly returns `Error: ...` strings for recoverable failures. `ask_agent` returns JSON with an `error` field when the named expert does not exist. Neither starts a successful execution, but both become completed evidence. The fetch callback retains the input URL as a retrieved source even when fetching failed.

**Independent reproduction**: Called the actual `web_fetch` tool with two distinct localhost paths, which its SSRF guard rejected before network access. Both outputs were `Error: private or local network addresses are not allowed`. Passing these real tool results through the current callback produced two completed receipts. An isolated in memory WorkModeService then accepted both research `collect` and `compare` as completed. Calling the actual `ask_agent` tool with a stub registry returning no matching expert yielded `{"error": "expert not found: nonexistent"}`; the callback classified it as `completed`, kind `dispatch`.

**Impact**: Deep Research can claim comparison without retrieving either source. Team or Multitask can count nonexistent experts as completed work. This violates the revision 3 requirement that reports and accepted requests are not proof of execution.

**Recommendation**: Classify the known tool result contracts or emit explicit semantic success/error receipts from those tools. Only attach retrieved sources after successful retrieval, and require a successful dispatch outcome before counting it. Cover plain error strings and JSON error results alongside `ToolMessage.status` errors.

### 2. Async dispatch completion arrives after the parent's integration opportunity

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/src/octop/infra/agents/teams/device_context.py:259`, especially lines 263 through 276. Related SDK order: `src/octop_harness/teams/inbox.py:310` through `318`.

The completed dispatch receipt is emitted only from `finish_job`, after the original inbox finish callback. The inbox first calls `_synthesize_reply`, which runs the parent expert to integrate the child's result, and only then calls `_finish`. During that parent invocation the dispatch receipt is still accepted, so `work_step` correctly rejects it as unfinished evidence. No subsequent parent invocation is scheduled after the receipt becomes completed.

**Independent reproduction**: Used the existing real Harness inbox fixture with its isolated fake agents and captured the installed tracker's receipt writes. Once the child had returned and the parent followup was running, the receipts were `['accepted']`. Only after releasing the parent response did they become `['accepted', 'completed']`.

**Impact**: The normal asynchronous Team flow cannot advance dispatch and integrate during its automatic followup. The final child in Multitask has the same issue. It requires an unrelated later invocation or remains blocked despite successful child work.

**Recommendation**: Persist the actual child result before invoking the parent integration callback. Keep delivery/followup status separate from child execution status, so a failed followup does not rewrite successful child execution as failure. Cover a parent followup that consumes the final receipt and completes the workflow.

### 3. Cowork can bypass the required user handoff entirely

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/src/octop/infra/execution/work_mode.py:147` through `152`.

The guard only requires a decision for `handoff` with status `needs_input`, or protects a decision that already exists. If the model submits `handoff` with status `completed` before creating a decision, `_validate_completion` has no Cowork constraint and the transition succeeds.

**Independent reproduction**: With an isolated in memory repository, completed `work`, then called `step` for `handoff` with the next version, `status='completed'`, an ordinary report, empty evidence, and no decision. The resulting workflow was completed and its handoff had no question, options, recommendation, user choice, or decision author.

**Impact**: The backend can display a completed Cowork workflow without the user handoff required by revision 3. The authenticated decision API cannot protect a decision that was never created.

**Recommendation**: Reject model completion of Cowork handoff regardless of whether an artifact exists. Require the pending decision artifact and let only the authenticated decision transition complete that stage. Add direct completion before artifact creation to the regression cases.

## Recheck of the previous four findings

| Previous finding | Resolution observed |
| --- | --- |
| Unknown device outcome displayed as failed | Resolved. ExecutionService reads the canonical operation status, preserves unknown for uncertain transport outcomes, and DeviceService writes late result and reconcile updates to the same operation event. Reviewed the disconnect after file commit regression and its same event identity assertions. |
| Nonzero command exit displayed as completed | Resolved. ExecutionService uses `result_status(action, result)`. The direct and queued regression asserts failed receipts for exit code 7. |
| Overlapping recovered parent and child cancellation remains unknown | Resolved for the reported case. Cancellation accepts `confirmed_stopped` after an earlier tree cleanup stopped the child. The helper distinguishes inaccessible processes from stopped identities. The added regression launches a real isolated parent and child and verifies both stop. |
| Git recovery location missing from saved receipt | Resolved. The bounded scalar receipt allowlist now includes the actual `recovery_copy` field. |

The earlier isolated probes recorded the first two status bugs and the real parent/child failure before these changes. This followup checked their corrections and regression assertions. No new defect was confirmed in the owner filtered workflow compare and swap or in the inspected UI decision request.

## Verification boundaries

Independent probes used the current SDK source, in memory SQLite, actual tools returning local errors, and the existing isolated inbox fixture. No production device, external web request, Git operation, release, or deployment was used. No application code was edited.

An attempted four case targeted pytest rerun was blocked at fixture setup by Windows temporary directory ACL errors (`PermissionError` and SQLite unable to open the temporary database). It is not counted as a passing rerun or as a product regression. Subsequent in memory and fake agent probes completed successfully and produced the evidence above.

Parent supplied evidence: request/device regressions 126 passed, modes/context/team 21 passed, SDK model router/Langfuse/RunEvents 17 passed, new UI 6 passed, related mypy 11 modules passed. These suites were not independently rerun in full.

Browser/preview, real fleet acceptance and full gates remain incomplete and are outside this incremental conclusion. Only this report was changed, as requested; scope and specification files were left untouched.
