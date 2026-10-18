# 0030 Latest paper-chat reliability audit and correction plan

Status: Historical audit/proposal; current implementation and acceptance are governed by 0031.
Date: 2026-10-17
Mode: CROSS-CUTTING / ENHANCEMENT
Related scope row: None present in this checkout.
Related specs: 0015, 0022, 0023, 0024, [0029](0029-attachment-resource-and-device-routing.md) and the implementation authority [0031](0031-collaboration-resources/index.md).

## Summary

The latest paper conversation is blocked by multiple integration defects beyond PDF reading: dispatch policy is silently lost through stale imported tool builders, history projection duplicates the final reply, and memory correction failed under SQLite contention while an overgeneralized diagnosis was added as a new active fact. Preserve the working expert/device boundaries and repair these contracts with tests at the actual invocation surfaces.

This is a diagnosis and proposed build plan. Application code, production services and memory contents were not changed during this audit.

## Audit scope and provenance

- Inspection date: 2026-10-17, Asia/Shanghai; audit clock checked at 18:24:44. User request: inspect the latest GPU conversation and give the complete observed problem set and solutions/status.
- Parent conversation: `thr_01M54J707VQ9Y4VD5QABWN62HH`, title 论文实验, expert `27N3HD`, messages 1–137. Latest user question is message 136; final answer is 137.
- Delegated conversation: `thr_01M54J707VQ9Y4VD5QABWN62HH~Y39HY4`, expert `Y39HY4`, messages 1–51. Four sync dispatches occur at parent messages 113, 115, 119 and 121.
- Production source changed after the earlier deployment record. Current `octop-hub` starts `/root/octopus-main/.venv/bin/octop run`, working directory `/root/octopus-main`, PID 1304106, start 17:02:14 CST. Read-only Git inspection: HEAD `a03a2839648b2ae34771aad6775dab114bce4068`, clean working tree.
- Actual imports: management under `/root/octopus-main/src/octop`; harness and memory under that checkout's `.venv/lib/python3.12/site-packages`. Final diagnostic probes used this actual Python and module path, not the earlier b15 package tree. An unchanged old package tree is not evidence of the currently running deployment.
- Database reads used SQLite `mode=ro`. Schema construction and history repros ran in separate processes, with no model or device calls. PDF extraction read the existing file without writing derivatives. No permission, service, history or memory mutation was performed.

## Confirmed findings and proposed fixes

### F01 — P1: Private-chat attachment capability gap

**Evidence:** Parent 77–107. Upload exists on controller (4,342,836 bytes). `read_file` rejects PDF and recommends shell extraction; shell belongs to GPU and cannot see controller storage. Current production pypdf extracted text from all 12 pages, 48,654 characters. `build_room_attachment_tool` is registered only for team hosts.

**Fix:** Implement the common attachment service/read tool in 0025, available in private chats, teams and explicitly delegated scopes. Resolve existing uploads server-side through BackendWorkspace. Keep project execution independent of attachment reading. Replace unreachable shell advice with an available, authorized operation. Preserve page provenance and bounded parsing.

### F02 — P1: Dispatch policy silently disappears at the actual tool entry

**Evidence:** Parent 121 really contains `target_policy=member_default` as an argument. Its child's final command still ran on GPU. In the actual production Python process, after `install_harness_target_patches()`:

| Builder | Fields exposed | Validation of target_policy |
|---|---|---|
| `teams.tools.build_team_tools` | Includes target_policy/device_id/target_kind/working_dir | Preserved |
| `middleware.peer.build_team_tools` | Only expert/message/mode/user_question | Silently dropped |
| `teams.team_manager.build_team_tools` | Same old fields | Silently dropped |

Both actual consumer modules imported the old function with `from ... import build_team_tools`; replacing the function on the original module does not replace these bindings. Pydantic's old schema ignores extra arguments. The pending policy stamp therefore never reaches dispatch, which legitimately falls back to inherit. The tool call's persisted original argument does not prove its execution-time acceptance.

**Fix:** Make policy a first-class harness schema/dispatch field through the real middleware and manager entry points. Pass a validated DispatchOptions object, not a monkey-patched function plus ambient ContextVar alone. Reject unsupported/unknown arguments explicitly. A short-term compatibility adapter must cover every live entry and verify their schema parity before agents start. Return requested policy and resolved target in the receipt; fail before child invocation on mismatch.

### F03 — P1: Delegation does not transfer bounded attachment access

**Evidence:** The cloud expert's file tools were correctly denied access to the GPU expert's private store. The parent sent an absolute path, not an authenticated attachment grant. At parent 119 it also wrote “I am the owner” into an agent-authored assignment; that statement has no authorization semantics. It did not make the rejected read succeed.

**Fix:** Resolve user intent through the authenticated dispatch context and issue a bounded grant for the specific attachment/version and child invocation. Revalidate on each read. Keep workspace isolation. Model-authored owner statements are task text, not credentials. Do not substitute a root shell for a denied storage read.

### F04 — P2: Next-turn selection is misused as an in-flight routing operation

**Evidence:** Parent 118 explicitly returns `effective=next_turn` and `current_context_unchanged=true`. The parent nevertheless dispatches again in the same run expecting a changed device. The child also selects its next-turn device, but the next inherited dispatch has an explicit parent target. The frozen-context behavior is intentional; the recovery path and model interpretation are inadequate.

**Fix:** Distinguish saved selection from this invocation's dispatch target in tools/UI and receipts. Use a functioning per-dispatch member_default/explicit override. If continuing on a different parent target is necessary, create a clearly identified new invocation after the current one. Do not thaw or mutate an active context. Stop repeated attempts when the same effective context and permanent failure recur.

### F05 — P1: Root progress and final answer are persisted again as a synthetic reply

**Evidence:** Parent 135 has no message ID and equals the exact concatenation of parent 115 content, parent 117 content and final 134 content. This is not evidence that the model generated another independent final. Current production `TurnHistoryTracker` independently reproduces `[user, progress, final, progress+final]` when given valid state-update and token events. `_inputs_cover_stream` looks for the complete concatenated stream inside one state message, fails across multiple assistant messages, and appends a synthetic message.

**Fix:** Reconcile by turn/invocation/message identity, with an explicit final marker. Use checkpoint/state messages as the authoritative completed answer; streaming fallback applies only to genuinely unpersisted content. Retain interrupted partial output with a partial marker. Do not discard legitimate progress or child records, and do not rely on substring containment for message identity. Repair existing display projection separately with reversible, recorded provenance; do not rewrite raw evidence blindly.

### F06 — P1: Memory replacement fails on SQLite writer contention

**Evidence:** Parent 129 reports `memory_update failed: OperationalError`. The production log at 17:35:21 shows `sqlite3.OperationalError: database is locked` in `Memory.replace_atom → save_atom`. The old atom remains active and has no successor. Parent 131 subsequently creates a new atom. These are separate operations, not an atomic replacement.

**Root-cause limit:** Lock contention is confirmed. The exact competing writer and SQLite extended busy code were not recorded; checkpoint/extraction concurrency is a hypothesis to reproduce, not a proven attribution.

**Fix:** Use short compare-and-swap replacement transactions with an appropriate write-acquisition strategy and bounded whole-transaction retry for transient SQLite busy/locked errors. Coordinate writers by physical database, considering checkpoint and memory writers, and keep network/model work outside the write transaction. Expose a retryable structured failure and keep the old fact authoritative until replacement succeeds. Verify rollback, successor and journal together. New writes must not be reported as successful correction of the old atom.

### F07 — P1: Temporary broken-runtime observations become permanent capability facts

**Evidence:** `atom/e0853d04-f708-4a06-9207-af5b3893db47` still claims the cloud expert has no configured default. Its actual default now is the server. New `atom/4f5b0e56-61e4-4219-96c7-a1ba822cdfc9` says dispatch from GPU cannot reach the cloud and should not be retried. Both are active, with `superseded_by=null` and `deprecated_at=null`. The new diagnosis misses F02 and treats one runtime defect as an enduring capability constraint.

**Fix:** Store operational observations with runtime/build provenance, time, evidence and scope; keep them distinct from durable user preferences. Resolve current capabilities/defaults from live tools before treating old operational memories as constraints. After a verified repair, retire/replace contradicted facts through the memory API, preserving history and correcting dependent summaries. Retry the actual failed replacement; adding another contradictory active fact is insufficient.

### F08 — P1: User's read-only request is advisory while runtime remains agentic

**Evidence:** Parent 1 says the project is currently read-only. The persisted conversation mode is craft; all relevant ExecutionContexts have `work_mode=agentic`. No project write was observed in this inspected exchange. Nonetheless the runtime had not enforced the requested read-only boundary.

**Fix:** Represent the user's read-only constraint in run policy and propagate the stricter policy to children. Use existing Ask/Plan observation controls where they meet the task; make any inability to run a requested command under that policy explicit. Do not infer permission to alter project files from general agentic mode. Expert memory maintenance and parser scratch writes have their own stated scope; do not conflate them with project write access.

### F09 — P2: Invocation completion hides business failure and recovery semantics

**Evidence:** All four dispatch events show completed, while the child responses describe blocked tasks. `ask_agent` mainly returns a response string. Memory failure similarly arrives as a plain failure sentence inside an otherwise successful tool response. The model must parse prose to determine result and whether it can retry.

**Fix:** Keep transport/invocation completion separate from task outcome. Return a typed outcome (`succeeded`, `blocked`, `failed`, `needs_input`), stable error code, retryability, requested/resolved target, child invocation/context and permitted next action. Tool failures should carry error semantics. Do not automatically copy large receipt histories into the model to compensate for missing status fields.

### F10 — P2: Child context preparation repeatedly creates context records

**Evidence:** Four child dispatches created 12 child ExecutionContext rows (three per dispatch), all sharing the parent's run ID but with different context IDs. Child expert identity is now correct; repeated restore/preparation still rebinds from parent context. Device operation receipts use the last of each set.

**Fix:** Resolve once per distinct child invocation and retain its immutable context across preparation, enrichment and restoration. Add a dispatch/invocation identity distinct from the root run, and preserve parent/root links for inspection. Restoration validates and reuses the already-bound context instead of creating another from the parent. Repeated calls to the same expert remain separate invocations even if they share a conversation.

### F11 — P2: Evidence and duplicated output inflate model context

**Evidence:** Parent work_step result 133 is 7,806 characters and includes historical receipts already represented elsewhere. Total stored parent message JSON is 572,160 characters at this cutoff. Parent 137 uses 341,154 input tokens. These measurements are different quantities: input tokens are not byte/character size or billing totals, and the audit does not attribute every token to one defect. F05, verbose receipt replay and repeated failed attempts are concrete avoidable contributors.

**Fix:** Return compact receipts and page details on demand. Enforce per-tool/turn output budgets with an inspectable full artifact, identify reused evidence by ID, and prevent duplication across state/history/stream projections. Stop repeated permanent errors. Keep actual per-request occupancy reporting, without using cumulative billing as occupancy or hiding missing evidence through silent truncation.

### F12 — P1: Verification covers helper branches but misses actual integration surfaces

**Evidence:** Target-policy tests call the patched `teams.tools.build_team_tools` or inject policy directly into configurable. Actual `middleware.peer` and `TeamManager.team_tools` retain an unpatched function reference. Earlier child-stream isolation does not test root progress/final aggregation (F05). Successful sequential memory correction checks do not exercise the writer contention seen at 17:35:21.

**Fix:** Test through real PeerAgentMiddleware construction and tool invocation, then resolved child context, actual backend route and outcome receipt. Cover sync/background, inherit/member_default/explicit, repeat calls, same-turn selection, concurrent users/devices and restrictive modes. Add valid stream/state replay and dual-writer memory regressions. On startup expose the actually installed schema/capability version; deployment validation records service command, source SHA, resolved dependency paths and runtime capability checks.

## Confirmed working boundaries / status corrections

- **Upload and existing parser:** The file is intact and actual production extraction succeeds for 12 text-layer pages. F01 is missing tool integration, not missing PDF bytes or a requirement for a new parser.
- **Callee identity rebinding:** The recent child contexts belong to Y39HY4 and the correct side thread. The latest child history has no `execution context belongs to another expert` errors. That part of the earlier fix is functioning; F02 is a distinct dispatch-policy entry defect.
- **Capacity metadata:** Parent 137 records max_tokens=1,000,000 and used/input_tokens=341,154, source=model_request. This confirms backend metadata at this cutoff, not a new visual verification of the occupancy UI.
- **Default binding visibility:** agent_list shows the cloud expert's owned default server binding; it is persisted in agents.config_json. Claims that its default is still empty are stale.
- **Device health:** Cloud and GPU have recent heartbeats and are not revoked. Device availability does not explain the blocked reads.
- **Frozen target and store isolation:** Cross-device operations and access to another expert's private store are being denied as designed. Their guards remain necessary; add explicit dispatch/resource capabilities rather than broadening OS permissions.
- **Memory tools:** memory_write is available and succeeded. This does not establish update reliability under contention or correction of older facts.
- **Nested-stream repair:** Current duplicate evidence is root progress plus root final, not a demonstrated recurrence of child answer streaming into the parent's final. Do not represent the earlier stream fix as solving every history path.

## Requirements

1. **AC1:** Existing private-chat PDF reads succeed while the GPU is offline, without project commands, re-upload or privilege changes (F01; detailed contract in 0025).
2. **AC2:** The actual runtime middleware and manager tools expose/validate the same dispatch schema. Unknown fields fail. member_default reaches the configured member device; explicit honors the requested authorized device; inherit retains caller target (F02, F12).
3. **AC3:** Each dispatch returns requested/resolved target and a stable child invocation/context. Repeated preparation is idempotent and does not mutate the caller's active target (F04, F09, F10).
4. **AC4:** A child can read only the specifically granted attachment; owner claims in message text do not grant authority, and private-store/device guards remain effective (F03).
5. **AC5:** A completed turn with progress and final produces one authoritative final, with no synthetic concatenation duplicate. Interrupted/replayed streams preserve valid partial evidence and remain idempotent (F05).
6. **AC6:** Memory replacement under concurrent writers either commits the complete successor/retirement/journal or returns a typed retryable failure after rollback. The tool never represents an additional write as replacement (F06, F09).
7. **AC7:** Runtime observations have source/build/time/scope; contradicted operational facts are superseded after verified repair and no longer block capability discovery (F07).
8. **AC8:** Explicit project read-only scope is enforced throughout parent/child runs and is inspectable separately from permitted memory/temporary-file operations (F08).
9. **AC9:** Tool receipts and conversation projection meet a defined output budget while original evidence remains inspectable. Capacity remains per-call metadata with provenance (F11).
10. **AC10:** Final verification uses the currently running service's source/dependencies and actual application tool/stream surfaces, and reports backend vs UI verification separately (F12).

## Decision / design direction

Keep existing storage and execution boundaries. Unify the three contracts that cross them:

- **AttachmentRef / ResourceGrant:** stable identity and narrow access, independent of machine path; implement 0025 rather than another private-chat-only parser.
- **DispatchOptions / DispatchReceipt:** requested policy, authorized resolved device, child invocation/context, parent/root links and typed task outcome; make it a supported harness interface instead of consumer-side monkey patches.
- **MessageIdentity / MemoryCorrectionReceipt:** turn/invocation/message identity for durable projection, explicit final/partial classification and atomic correction receipts with retryable errors.

The same immutable context must reach the tool schema, dispatch, project backend, history and inspection layers. The same resource identity must reach upload, grants, parsing, child access and citations. Prompts explain these contracts; they do not substitute for enforcement.

## Build plan

1. **Stabilize contracts first** (AC2, AC3, AC5, AC10). Reproduce F02 and F05 via real construction paths; fix first-class dispatch options, strict validation, resolved receipts and root-message reconciliation. No OS or device permission changes.
2. **Make current document task usable** (AC1, AC4). Implement phase 1 of 0025 with old-upload support. Prove the existing production attachment reads through the application tool, not only a standalone parser.
3. **Stabilize memory correction and policy propagation** (AC6–AC8). Reproduce busy/locked rollback and whole-transaction retry using concurrent writers; enforce read-only constraints and preserve child restrictions. After verified fixes, prepare a bounded, auditable correction of the two identified operational facts; keep raw history.
4. **Finish resource lifecycle and output budgets** (AC3, AC4, AC9). Add the remaining resource/grant/cache and invocation identity work, bounded receipts, optional device materialization and failure-aware retry behavior.
5. **Integrated gate** (all AC). Run repository checks for touched code and behavioral verification using actual installed entry points. Validate runtime source/version/schema manifest, Windows/Linux routing as applicable, and the real chat flow with no external-model calls counted as unit-test evidence. Deployment and any memory mutation need their own authorized implementation scope; this proposal performs neither.

## Consequences / limits

- This inventory covers the latest parent/child exchange and its involved runtime paths; it does not claim an exhaustive audit of unrelated product modules.
- Current evidence supports 12 findings with distinct fixes. Some are missing product contracts, not failed security boundaries.
- Correcting the schema path alone restores target-policy handling but cannot grant cross-expert attachment reads; both contracts are needed.
- Centralized attachment reading resolves this PDF task without requiring shell access to controller internals.
- No application source edits, production restart, live task dispatch or memory replacement were performed as part of this review.

## References

- Production observations above: parent message numbers, child context records, current service paths and the 17:35:21 application exception.
- Source paths: `infra/agents/teams/{target_visibility,device_context,team_manager}.py`; `infra/agents/manager.py`; `infra/history/projection.py`; `infra/agents/middleware/binary_read_guard.py`.
- Harness paths: `middleware/peer.py`, `teams/{tools,team_manager}.py`, `memory/management.py`, `builtin/tools/memory_tools.py`.
- [Pydantic extra-data handling](https://docs.pydantic.dev/latest/concepts/models/#extra-data): extra model inputs are ignored by default unless explicitly configured otherwise; the production schema probe directly confirmed this behavior here.
