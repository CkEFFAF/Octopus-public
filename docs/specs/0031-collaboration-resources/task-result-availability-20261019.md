# Invocation-scoped task-result tool availability

Date: 2026-10-19 (Asia/Shanghai)
Status: implemented and independently approved; final isolated integration gate and hotfix PR submission pending. The user will merge; deployment is outside the current scope.
Parent: [Explicit collaboration task results](task-results-20261018.md), CR2 and CR7.
Coordinator owns this decision; coder owns implementation; independent reviewer owns acceptance.

## Observed and expected

The user confirmed the earlier Chat Completions tool-content 400 no longer occurs after the reviewed Harness update. A remaining direct-conversation call to `report_task_result` returns `TASK_RESULT_DENIED`, `retryable=false`, and the generic message `Task result could not be recorded.`

The coder reproduced the same result through the actual StructuredTool with a normal direct-message configurable containing user, agent_id, thread_id and conversation_mode, but no child invocation. Repository lookup used an empty invocation ID. AgentManager unconditionally registers the tool; its description asks the model to report before its final answer without stating the delegation prerequisite. TaskResultService correctly rejects a missing authenticated invocation binding. This confirms a tool availability/instruction defect, not a reason to relax task ownership.

Expected: a direct conversation answers normally without being offered a delegated-task reporting tool. A running, correctly bound child invocation can report, and its result remains pending until trusted final-answer persistence. Stale direct-history calls receive a clear prerequisite message without creating a task or claiming success.

## Decision

Register the tool on an application-owned AgentMiddleware through its public `tools` attribute, and filter model-visible tools per request. Do not place it in the static parent tool list inherited by inline `task` subagents. Mount the middleware in AgentManager's chain before Harness tool search; the installed Harness places user middleware before peer guidance, conversation-mode filtering and tool search. Verify actual graph assembly before accepting this registration seam. No Harness source or wheel change is expected.

Do not mutate Agent-wide `tools_disabled`, cached tool objects or shared configuration. A single Agent can serve ordinary and delegated turns concurrently. Use the current LangGraph configurable, never model-provided authority fields. Resolve reporting eligibility read-only from the existing owner-scoped invocation repository and exact callee/child binding. Reuse a small application-owned binding resolver between availability and report validation where practical, preserving existing report semantics.

Retain the report service as the execution authority. Visibility is assistance to the model and does not grant permission. Keep owner/callee/child checks, child-bound requirement, resource provenance, running state, candidate CAS/idempotency, trusted final-answer evidence and terminal lifecycle rules intact.

## Acceptance criteria

- AV1: Ordinary direct conversations and requests lacking an invocation ID do not advertise `report_task_result`. Other tools are unchanged. Filtering works for both sync and async model requests and does not mutate the original request.
- AV2: Show the tool only for the current authenticated owner's running invocation with exact callee agent and child thread plus the trusted child-bound flag. Missing, forged, cross-owner, wrong-agent, wrong-thread and terminal bindings do not expose it. Existing filters may still remove it; this middleware must never re-add a tool removed by another policy.
- AV3: A stale direct-conversation call with no invocation ID returns a non-success prerequisite result with code `TASK_RESULT_NOT_APPLICABLE`, `retryable=false`, and localized guidance: only a running delegated child task can report; answer directly in an ordinary conversation and do not retry. Keep the existing error result shape for compatibility. No invocation, event, report candidate or receipt is created. If an invocation ID is supplied but binding fails, retain the generic `TASK_RESULT_DENIED` response and do not disclose another task's existence or identifiers.
- AV4: Tool description explicitly limits reporting to an assigned delegated task in the current child invocation. Do not tell the model to manufacture a dispatch merely to report. English/Chinese user-facing guidance has parity. Existing valid child assignment guidance remains scoped to real delegation.
- AV5: A real installed-Harness `ask_agent` dispatch using synthetic agents still exposes and successfully submits the report in its bound child request, persists pending then commits outcome with a real final answer. Exercise sync and async dispatch paths. Ordinary tool denial is not evidence that genuine delegated reporting is broken or fixed.
- AV6: The same middleware/Agent reused in direct -> child -> direct turns and concurrent distinct configurations has no tool-visibility leakage. Deferred/client tool search does not reveal or reload the hidden report tool in a direct request. Cover actual assembled middleware registration and common tool object/dictionary representations supported by ModelRequest.
- AV7: Existing security and lifecycle regressions remain green: cross-owner/binding/resource denial, conflicting reports, duplicate replay, cancellation, missing final evidence and terminal-persistence failure. No production job is replayed, no history rewritten and no real provider/device action is required for verification.
- AV8: Inline `task` helpers, including the default general-purpose helper and workspace-declared inherited-tool helpers, do not inherit `report_task_result`. They have no independent collaboration invocation to report. The owning delegated expert reports its own result after integrating helpers. Verify the actual installed DeepAgents/Harness graph, not just the top-level request list. Nested real `ask_agent` delegation uses each child's own exact binding, and restoring the parent context cannot report against the grandchild. Streaming model requests use the same availability policy; missing runtime config and restart-recovered non-running invocations hide the tool.
- AV9: Distinguish a real authorization rejection from an unexpected internal failure. A reproduced repository RuntimeError currently becomes `TASK_RESULT_DENIED` without diagnostic logging. Preserve expected OctopError denial and established `TASK_RESULT_*` ValueError codes; unexpected failures return `TASK_RESULT_UNAVAILABLE` with generic localized unavailable text and `retryable=false` because commit state can be unknown. Record a bounded internal diagnostic containing the exception class, without raw exception text, traceback, configurable, summary or resource IDs. Verify a fault before persistence and an ambiguous failure after persistence do not forge a success acknowledgment or expose private sentinels.
- AV10: Availability checks are read-only assistance, not the business operation. If the middleware's own binding lookup unexpectedly fails, fail closed by removing only the reporting tool and logging only the safe exception class. Keep this catch around that lookup, never around the downstream model handler or other middleware. Normal answers can continue; missing report candidates must remain unknown under the existing lifecycle, with no synthetic success. Verify this degraded lookup path separately from tool execution: only actual report execution faults return the AV9 tool error. Do not add retries or fabricate model-facing tool messages for an eligibility probe.

AV9 classification uses an exact allowlist for existing canonical codes (`TASK_RESULT_NOT_RUNNING`, `TASK_RESULT_INVALID`, `TASK_RESULT_CONFLICT`, `TASK_RESULT_EVIDENCE_MISSING`), not a prefix match on arbitrary exception text. Preserve Pydantic input-validation denial separately from unexpected infrastructure errors. AV10 treats OctopError as an expected binding denial; unexpected TypeError/ValueError (including storage decode errors) also require the bounded exception-class diagnostic before hiding the tool.

## Build and review plan

1. Establish red regression for model-visible availability and direct tool fallback (AV1-3), retaining the coder's already observed StructuredTool reproduction.
2. Implement a focused application middleware and registration plus bounded service/description/localization changes (AV1-4, AV8-10). Prefer `src/octop/infra/agents/middleware/task_results.py`, existing `teams/task_results.py`, AgentManager and the existing zh/en locale files. Preserve unrelated workspace changes.
3. Verify real installed dependency integration, helper inheritance, nested/streaming lifecycle and request reuse/search behavior, then run affected suites and project-required gates (AV5-10). Tie results to final source hashes; record unavailable gates explicitly.
4. Independent reviewer checks exact diff and authority boundaries. Publication follows the established hotfix PR process. The user's latest instruction is to submit the PR and let the user merge; do not merge or deploy it.

## Scope and limits

This change does not grant task-report permission to ordinary conversations, create synthetic accepted jobs or convert a normal answer into automatic business success. It does not repair the separate legacy aggregate-text duplication candidate. The catch-all classification extension is limited to the reproduced internal-fault behavior in AV9 and does not introduce retries or change lifecycle persistence.

The initial reproduction is local and structural. The user's production account of a direct conversation is consistent with it, but no private production turn was inspected for this second incident. Acceptance must distinguish this confirmed direct-session defect from a hypothetical failure of real delegated reporting.

## Final source acceptance

The GPT-6.1 medium coder implemented the repair and observed failing regressions before the fixes. The expanded intermediate application snapshot passed 236 affected tests; subsequent final error-classification corrections passed all 51 availability/task-result tests. Ruff/format, strict Mypy for the two business modules and CRLF-aware diff checks passed. These focused results are not a claim of a final full-repository gate.

The user-designated GPT-5.6 Luna high reviewer independently approved AV1-AV10 and the exact nine implementation/test files with no blocking finding. Its sorted path-plus-lowercase-SHA256 fingerprint is `0af6c041733b85a03b2476527c35304e4357af5f10abc669ef9242f0912c4783`. Reviewer pytest attempts were blocked by Windows temporary-directory ACLs; the reviewer did not relabel those attempts as passing tests. The final isolated application assembly retains main's existing tooltext Harness wheel and queue changes and must report its own integration-gate outcome before merge.
