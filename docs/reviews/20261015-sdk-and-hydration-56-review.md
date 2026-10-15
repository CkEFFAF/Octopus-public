# SDK and session selection incremental review

Date: 2026-10-15
Reviewer: independent `gpt-5.6-sol`, high effort. Main baseline `28a97280`; SDK baseline `1774fe9`.
Contract: [0015 revision 3](../specs/0015-device-execution-and-context-inspection.md).

This records findings delivered by the reviewer before its usage limit ended the turn. The reviewer did not finish a final report or re-review the subsequent fixes. Fix evidence below is the integrating agent's verification, not an independent clean review.

## Findings and repairs

| Severity | Confirmed issue | Implemented repair |
| --- | --- | --- |
| Blocker | Snapshot text was truncated before PII detection. A phone or resident ID crossing the boundary could leak almost completely. Message/tool-call IDs were raw and unbounded; component count was unbounded. | Redact complete values before retention, bound identifiers/metadata and component detail count, preserve full composition/token estimates and publish truncation flags. API/UI distinguish retained detail from full totals. |
| Major | Caller-controlled `lc_source` and memory recall markers could make ordinary external input appear to be a generated summary or skill. | Strip reserved internal attribution markers at `ChatRequest` normalization without mutating caller objects. Runtime middleware and checkpointed summaries/skills retain their markers. |
| Major | Set-based compression comparison lost removals when two messages had identical content but different IDs. | Compare ordered identity/fingerprint pairs and consume retained multiplicities; never invent IDs for unlabelled messages. |
| Blocker | ACP prompt cancellation escaped `suppress(Exception)` as `CancelledError`, aborting shutdown after the registry was cleared. Later sessions could remain alive. | Contain prompt cancellation explicitly and close all conversations/services with independent result collection. Regressions cover two active prompts and a failed cleanup. |
| Major | Failed session-selection hydration allowed expert/account fallback and empty target serialization, potentially clearing a saved target or executing on another target. | Existing-thread target readiness is explicit (`unknown/loading/ready/error`); sending and new execution panes require ready. Failed restoration remains unavailable and can be retried. |
| Major | Changing work mode while selection loaded replaced the whole selection object, causing hydration of the stored device/directory to be discarded. | Merge unchanged fields independently and preserve the user's changed mode. |
| Minor | A delayed restore could overwrite an unsaved directory draft. | Disable target/directory changes until restoration completes. |

## Integration checks

- Main target hydration, queued sends, dock scope and payload regression: **58 passed**, TypeScript and production build passed (`.cache/architecture-hydration-final.log`, `.cache/architecture-hydration-build.log`). Queued explicit selections retain their original scoped device, directory and mode after the original picker unmounts. Clearing a selection explicitly persists null; ordinary empty overrides are omitted.
- SDK affected snapshot/provenance/compression/ACP/request regression: **76 passed**, affected strict mypy **9 modules**. Full Windows commit hook: **1678 passed, 28 skipped**, strict mypy **190 modules**, Ruff clean (`.cache/sdk-post2-commit-gate.log`, SDK commit `2252dd5`).
- Linux SDK full run on locked DeepAgents 0.7.21 exposed one new test depending on the optional `pinned_skills` state available in the main environment's 0.7.24. The compatibility regression now injects a real loaded skill through the public middleware boundary and checks checkpoint reuse. No product behavior was skipped. Final SDK commit `22514b4` passed Windows **1678/28 skipped** and Linux **1684/22 skipped**, both with mypy **190 modules** and Ruff clean. GitHub Python CI and CodeQL passed; SDK PR #2 merged and post2 was published.
- Real authenticated preview: saved explicit local target and native project directory survive reload without sending a chat message. New file and Git panes open on that directory; actual Git status and side-by-side diff load. Browser creation and navigation use the persisted context. No preview fixture ownership, permissions or account default was changed.

## Remaining gate

The incremental independent recheck remains unavailable and is not represented as passed. Fixes were checked by the integrating agent and verified by regressions, dual-platform SDK gates and GitHub CI. SDK publication is complete; main release/CI and actual registered-device desktop/input/reconnect acceptance remain required before declaring architecture delivery complete. Fleet production remains b10 at this checkpoint.
