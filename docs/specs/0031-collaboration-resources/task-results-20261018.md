# Explicit collaboration task results

Date: 2026-10-18 (Asia/Shanghai)
Revision: 2026-10-18.1
Status: implemented, independently source-reviewed and locally verified; Git publication and controlled rollout in progress.
Parent: [0031](index.md), revision 2026-10-18.4.
Baseline: 323f585efd3a9aafe279e936f14f5114275fbf7d plus the isolated UI patch in hotfix/resource-delivery-cards. Preserve the unrelated live-message-steering working tree.

## Evidence and problem

Read-only production inspection located the user-identified GPU manager conversation asking the cloud server expert for today's traffic. The user reports that the expert has finished while the card still shows an unknown result. The relevant invocation has complete accepted/target/started/completed events, transport_status=completed, task_outcome=unknown, error_code=null, history_start=0 and history_end=41. Exact production identifiers are retained only in local operational evidence, not in this publishable source record. The child final public answer and parent response exist. No resource was published in this scope; zero file artifacts is accurate.

Source inspection found a task-outcome consumer but no producer: Harness TeamManager._result_receipt accepts a trusted structured dispatch_receipt; the application currently returns child messages/text without reporting a business outcome. This is not a polling failure. The user explicitly requires transport status and task outcome to remain separate. A completed call or ordinary answer cannot be automatically upgraded to task success.

## Decisions and acceptance

| ID | Required behavior |
| --- | --- |
| CR1 | Preserve transport_status and task_outcome as separate fields and UI labels. A normal completed call can have succeeded, blocked, failed, needs_input or unknown business outcome. Clearly label reported results as expert-reported, not human acceptance or automatic scientific verification. |
| CR2 | Provide report_task_result(outcome, summary, resource_ids=[]) as an invocation-scoped typed child tool. It accepts no owner, agent, thread, invocation or device authority parameters. Resolve those exclusively from the authenticated runtime and bound invocation. Reject calls outside the exact current owner/callee/child binding or without a running invocation. |
| CR3 | The outcome is one of succeeded, blocked, failed, needs_input; summary is nonempty public text, at most 2000 characters; resource_ids is unique and at most 20 exact immutable resource references. File evidence must already be published by this invocation's callee/child with the same owner/root scope; mere read grants or a path do not constitute produced evidence. Pure text tasks may use no resources. |
| CR4 | Store the first report as a pending candidate with its content fingerprint and a bounded append-only event in the existing invocation JSON/CAS repository. Identical replay is idempotent; conflicting reports cannot overwrite it. A report submission is not yet a committed task outcome and does not end execution. |
| CR5 | On normal child return, persist its public final answer through the existing after-peer hook. Validate an actual nonempty final assistant message, excluding tool calls and reasoning, within this invocation's child history range, and bind its exact seq plus any immutable resource/version references. Only the host authors the trusted receipt from this candidate and evidence. The lifecycle's terminal state/event write commits transport completion and the independent task outcome together. No report means unknown. |
| CR6 | Reuse the installed Harness public after-peer/lifecycle hooks; no tool/schema monkeypatch or cross-repository runtime fork. The after-peer hook currently catches exceptions, so a failed history/evidence step must never leave a forged succeeded receipt in the returned payload. Missing evidence, persistence conflict, cancellation or abnormal child return keeps the report provisional and the task outcome unknown, with an inspectable bounded reason. Existing receipt-persistence error handling must not falsely acknowledge a stored completion. |
| CR7 | Tool descriptions and the bound child assignment/system guidance explicitly instruct the expert to report its business outcome before its final public response. Reported failure/blocked/needs_input can accompany a normally completed call. A report itself is an output/telemetry operation, not permission for device writes; it must work for read-only observation tasks without weakening Ask/Plan execution restrictions. |
| CR8 | Public owner-scoped inspection exposes the committed report summary, its expert-reported provenance, and safe evidence references. Do not expose bound config/history internals, reasoning, raw private paths or arbitrary provider errors. Legacy completed records derive reply_received from bounded, authorized public history evidence; show call completion, received reply and unconfirmed task outcome separately. Do not rewrite production history or infer a historical outcome from prose. |
| CR9 | Refresh/replay/reconnect preserve the two independent statuses and do not duplicate reports or cards. Keep resource publication, explicit target delivery and task outcome independent. No synthetic artifact is generated for ordinary text replies. New UI/tool/error copy has zh/en parity. |

## Implementation seam and ownership

The collaboration coder owns application collaboration service, a bounded task-result tool builder and its registration in AgentManager, the existing record_peer_turn integration, API/TypeScript models, CollaborationPanel and associated tests. Prefer a focused collaboration result tool module rather than mixing unrelated device transfer behavior into ResourceService. Root owns this spec and architecture; sharing writer owns its separate UI files. Shared locale files and any shared AgentManager edits have one designated writer; coordinate before editing.

The existing record_peer_turn hook receives the mutable trusted host result before Harness _result_receipt. Use this supported seam to attach a validated host receipt. Treat candidate/evidence CAS conflicts explicitly; never use unconditional writes, auto-repeat a child, or accept model-supplied receipt metadata as authority. Do not broadly change existing transport transition rules. Keep the current immutable resource/grant and child-owner checks. No schema migration is expected for bounded invocation JSON fields; report an incompatibility before adding a table or changing a Harness signature.

## Build and verification

1. Implement report validation and pending candidate persistence (CR2-4). Verify actual assembled tool schema, authenticated owner/callee/child binding, cross-owner rejection, explicit extra-field rejection, exact replay, conflicting report and concurrent CAS failure.
2. Wire normal final-message persistence and trusted receipt/lifecycle completion (CR1, CR5-7). Exercise real installed Harness sync and async entrypoints with a report, without a report, task failed with call completed, missing final evidence, receipt-save conflict, cancellation and tool replay. A tool unit test alone is insufficient.
3. Extend bounded inspection and two-label UI (CR8-9). Verify historical completed+public reply remains task unknown with a clear explanation; completed without reply is not labeled replied; task success only appears for committed expert report. Keep zero file resources for pure text tasks. Exercise cross-account detail and reconnect/pagination.
4. Review the integrated fixed diff independently, run affected suites and repository gates, and build/inspect desktop and narrow UI. Use synthetic test data; production inspection remains read-only until the separately authorized deployment stage. Preserve GPU experiment tasks/processes and device identity during deployment. Record actual gate outcomes rather than reuse historical failures.

## Limits

An expert report records the expert's structured claim plus traceable output evidence. It is not proof of factual, scientific or financial correctness. Human acceptance and domain-specific automated validators are not added in this repair. Existing records remain truthful; no live task is replayed to populate missing results.

## Compatibility delta, 2026-10-18.2

The actual installed Harness integration test found a bounded runtime defect: when terminal lifecycle persistence raises, TeamManager._observe_peer changes transport_status to unknown but retains a preexisting succeeded task_outcome. This can acknowledge an uncommitted business success. An app-only workaround that always returns unknown while the database stores success would create another inconsistent authority and is rejected.

Root authorizes one minimal Harness correction: terminal receipt-persistence failure also resets task_outcome to unknown while preserving the existing PEER_RECEIPT_PERSISTENCE_FAILED error. Public hook signatures and observer return semantics are unchanged. Normal validated host receipts still carry their independent business result. Add actual sync/async persistence-failure regressions, preserve existing Harness behavior elsewhere, and review the exact dependency delta.

This supersedes only the earlier assumption that no Harness source change is necessary. Do not modify shared dirty Harness source or installed site-packages. Build a reproducible reviewed vendor wheel from an isolated matching source, update the portable source manifest and frozen lock as needed, and verify the actual installed wheel and its hashes before integrated gates and deployment. A source PYTHONPATH is not final dependency evidence.

## Implementation evidence, 2026-10-18

The application implementation and isolated Harness correction are frozen for final integrated review/gates. The result coder reports 141 affected backend tests passing, then 37 actual-installed-wheel matrix/API/mode checks passing after the final rebuild. Frontend CollaborationPanel/Dock16 tests and TypeScript pass; the new three source modules pass strict mypy; the isolated Harness terminal-failure regression passes. These are focused evidence, not a green full repository gate.

Private Harness artifact: `octop_harness-1.0.2.post3+taskresults.1-py3-none-any.whl`, SHA256 `5f96288e6617abb5e7d8ffeea61b39674e61186a81a30a82830737accbb9c227`. Its source/wheel/installed package369 files match the manifest. Source is isolated from commit6636ce2c4fed85c92f37da66459a218ddf158aef; the original live-message-steering dirty worktree was preserved. The reproducible dependency patch SHA256 is `ea08a50a3473feef7e0de5417a566f878a72645b27f8f120b515f1ab4ac61d54`; manifest SHA256 `152004351eb9da8586eea9a4faef96c57c43e17d894a1771215e02718b6de5d0`. The relative wheel source, precise dependency pin, lock and Git artifact allowlist are updated. No Harness source PYTHONPATH was used for final installed-artifact tests.

Independent review identified and the coder fixed two legacy-derivation errors: unavailable/deleted child history now yields no reply evidence without breaking the authorized parent listing; a trailing tool-call-only assistant does not let an earlier intermediate answer masquerade as the final reply. Actual regressions cover both, including cross-owner denial and already-persisted-final deduplication. Pending/ready candidates and fingerprints remain private; public result fields are explicitly typed and expose only committed expert-reported evidence.

Final full gate, final independent sign-off, Git publication and live deployment remain pending. Do not claim deployed acceptance from the earlier UI fixture or focused tests.

## Full-gate correction record

The first current combined make all completed with exit2:4934 tests passed,159 skipped,3 failed in968.37seconds. Ruff/format and mypy completed successfully. The three regressions were exact legacy expectations: two manager tool-set assertions omitted the newly registered report_task_result, and one gateway dispatch test expected an assignment without the newly required localized result-reporting instruction.

The coder changed only those expectations in two existing test files, preserving exact tool sets, the complete original assignment and localized guidance, and all room-history/peek/take assertions. Both complete affected suites then passed:143 tests. Ruff/format and CRLF-aware diff checks pass. Production code and the independently reviewed24-file fingerprint are unchanged. The original red gate remains recorded as red; a new final full gate is required and is in progress.

## Final local acceptance

The corrected combined source passed actual `make all PYTEST_JOBS=4` with exit0:4939 passed,157 skipped,20 warnings in729.36seconds. Ruff/format and mypy passed before pytest. Full stdout/stderr and exit marker are retained in workspace `ops/resource-delivery-ui/final-make-all.log`. The earlier3-failure run remains separately recorded; it was not relabeled as green.

Independent GPT-6 Luna high review recomputed the24-file result/dependency fingerprint `a66e60dd513921c8db0d6bd685cd077fe2d93970e0720d62af38f9d5638d380f` and the two-test correction fingerprint `efeab00dab6080c46cc894a280ff702047fe34443a83bf9eb2a0112e3d1f4073`, with no remaining substantive finding. Sharing layout and snapshot behavior also passed read-only source review.

A fresh real-component Edge fixture verified independent call/result labels for succeeded, failed, historical unknown with/without reply and running at1280/375. Source provenance/summary is visible; unknown remains neutral. Hidden reasoning/system test sentinels are absent. Scroll, verified synthetic download, preview and Escape work. Root inspected desktop/mobile screenshots in `ops/resource-delivery-ui/results-ui-*.png`. These are synthetic local UI checks; live production acceptance is a separate controlled rollout step, currently in progress.
