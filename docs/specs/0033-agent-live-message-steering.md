# 0033. Runtime message steering for agent turns

**Date**: 2026-10-18 (Asia/Shanghai)
**Revision**: 5
**Status**: Implemented (revisions4 and5 locally verified; not released)
**Contract**: During a running agent turn, submitting a message defaults to queue. Each queued message offers explicit interrupt-and-insert and withdraw actions. “Run now” must account for LLM and tool boundaries.
**Implementation**: Initial feature and UI PR31 merged through PR32 (`5eb213320f291f410efb6bf754e1e1583ed71c49`) and deployed on 2026-10-19 with combined Harness `1.0.2.post4.dev1+taskresults.1`. Revision3 follows the user's clarified queue-first UI flow; its validation and release are tracked in the existing progress document.

## Summary

Users can queue, insert after current tools finish, explicitly interrupt tool waits and insert immediately, or withdraw a queued message. The interface reports acknowledged waiting, interrupting, applied and failure states. Immediate mode returns an interrupted result for each cancelled call, without replaying it or claiming that external/background work has stopped.

Revision4 is authorized by the user's 2026-10-21 report that a `sleep 900` tool blocks insertion and explicit request to adjust the UI. It supersedes the revision3 unconditional no-tool-cancellation rule only for the new immediate action. Previous validation does not establish revision4 behavior; current evidence belongs in `docs/progress-agent-live-message-steering.md`.

Revision5 addresses the user's follow-up screenshots of permanently waiting and unconfirmed receipts. Read-only production evidence found the inserted human message already present while its receipt remained accepted; scheduled delivery consumed steering events without observing or broadcasting them. Revision4 runtime code is unchanged; receipt/lifecycle and UI evidence must be refreshed.

## Context

Today the dashboard keeps queued chat messages only in React memory. They are sent FIFO after a stream ends, disappear on refresh, and have no server acknowledgement. There is no run-control path: the WebSocket `cancel` command cancels the whole Harness stream. Harness races that cancellation against graph iteration and closes the iterator, so it can interrupt an LLM or a tool without distinguishing their side effects.

This feature crosses the Dashboard, authenticated chat WebSocket, gateway processor, agent manager and Harness graph lifecycle. The active GPU-manager conversation is production user data and must not be used for interruption tests.

## Requirements

- **AC-1**: While a turn is active, the user can choose queue, run now, or withdraw a queued message. Queue order is FIFO and every accepted action has a visible acknowledged status.
- **AC-2**: A queued message survives page refresh and reconnect; withdrawing it succeeds only while its status is queued. A retry with the same command ID does not insert it twice.
- **AC-3**: Run-now requests bind to the authenticated owner, agent, thread and active run. Invalid, stale, duplicate, or cross-owner requests fail without changing the run.
- **AC-4**: Run-now during LLM generation stops that generation at a supported cooperative boundary, retains any emitted partial assistant text as an explicitly interrupted message, applies the user's new message once, then resumes from the thread checkpoint.
- **AC-5**: At LLM-before/after and tool-before/after boundaries, the new user message is applied before the next LLM call. A pending tool call is re-evaluated and must not be executed from stale model output.
- **AC-6**: Default insertion during tool execution still waits for completion and never replays the tool. The explicit immediate action cancels the current tool handler waits, emits one correctly paired interrupted ToolMessage per call, then applies the new user message before the next LLM call. A cancellation-resistant backend cannot block insertion or append a late tool result to the checkpoint. External work is reported as unconfirmed, never automatically retried.
- **AC-7**: UI status identifies the observed phase (`llm_before`, `llm_running`, `llm_after`, `tool_before`, `tool_running`, `tool_after`, terminal or paused status) and uses server acknowledgements as its source. It does not claim an insertion was applied before the server confirms it.
- **AC-8**: Normal queued turns, HITL pauses, attachment metadata, model and execution-selection snapshots preserve existing behavior. A queue flush must not bypass an open HITL pause.
- **AC-9**: Phase-aware control and inserted-message processing are covered by Harness, gateway/API, and Dashboard tests using synthetic threads; production conversations are not interrupted for verification.
- **AC-10**: Sending while the local agent is running queues by default and never implicitly interrupts. Each queue row displays its acknowledged state and explicit insert/withdraw icon buttons. Insert acts on that exact queued message without changing an unsent draft. Withdraw retrieves that exact message for editing, confirming before replacing an existing draft. The independent stop control remains available while typing.
- **AC-11**: Promoting a queued item to insertion is one server operation using its existing command ID and stored text. Promotion races atomically with dispatch and withdrawal; exactly one wins. Explicit runtime rejection preserves the original queued item and FIFO position. Uncertain outcomes are visible and never automatically replayed. Attachments and slash commands remain queued.
- **AC-12**: Each queue row exposes separately labelled insert-after-tools and interrupt-and-insert-now actions. Both honor pending, inactive, attachment and command guards. Immediate mode is persisted and forwarded with the authenticated run ID; retries do not change an acknowledged operation's mode. Live tool results visibly identify user interruption and the possibility of external work continuing. Desktop and narrow-screen layouts remain usable.
- **AC-13**: Dashboard scheduled/self-reminder runs persist and broadcast run phases, insertion application and inserted-user events, preserving prior visible assistant output before the inserted user. Success, failure and cancellation end the visible stream. Missed receipts are repaired only when the exact inserted human ID exists in that owned thread's canonical history. Unproven outcomes stay unconfirmed. Users can dismiss an unconfirmed/failed receipt without deleting its audit payload, cancelling work or replaying input; pending work cannot be dismissed.

## Decision

**Chosen option**: Fix the existing chat queue in place and add a phase-aware steering control path to the existing Harness stream; do not add a new broker or replace the chat transport.

Use authenticated REST commands and the existing WebSocket event stream. Reuse `run_events` for durable receipts, with atomic compare-and-set dispatch/withdraw and a per-thread admission transaction. Harness owns model/tool middleware and runtime identity. The gateway owns persistence, FIFO dispatch under the same session lock as ordinary turns, HITL deferral and history projection. Dashboard waits for server acknowledgement before clearing the submitted draft.

## Feature design

Queue: `queued -> withdrawn | dispatching -> applied | completed | paused | failed | cancelled | unknown`. Direct insertion: `requested -> accepted -> applied`; rejected admission reports inactive/stale_run/busy/conflict. A started request of uncertain outcome becomes `unknown` on recovery and is never automatically replayed. An accepted direct request still pending at a pause/termination becomes `unknown`.

| Observed phase | Direct insertion behavior |
|---|---|
| LLM before | Append the user message before generation |
| LLM running | Cancel and drain only the model handler, preserve public partial text, then append user and generate again |
| LLM after | Append and jump back to the model; a late request at graph exit starts a fresh model step from the finished checkpoint |
| Tool before | Supersede tool calls not yet admitted, then replan |
| Tool running (default) | Let admitted tools finish once; skip stale calls not yet started |
| Tool running (explicit immediate mode) | Cancel tool handler waits, allow bounded cancellation cleanup, emit interrupted results, then apply the message; ignore late handler returns |
| Tool after | Append before the next model call |
| HITL paused | Keep the approval pause; do not start queued work or bypass with direct insertion |

Ordinary streaming and HITL resume use the same run-control wrapper. The graph iterator is not cancelled by insertion. Existing explicit cancellation is separate. Admission and tool start are synchronous on the event loop until their first await.

**API**: GET/POST `/agents/{agent}/threads/{thread}/inputs`, DELETE `.../inputs/{command}`, POST `.../inputs/steer`. Requests bind command ID, thread and run ID to the authenticated owner. The existing WebSocket supports the same steer command and streams `run_phase`, `steering_applied` and inserted `user` events. Native local one-to-one chats use server persistence. Bridge/team chats retain their previous behavior and do not advertise direct insertion.

**Snapshot boundary**: Queue captures attachments, model, composer context, approval policy and explicit execution target. Admission validates without changing the running thread selection. Direct insertion currently accepts plain text and inherits the active invocation settings; attachments, slash commands and setting changes use queue. The UI states this boundary and retains the draft on rejection.

**Key invariants**:

- Default insertion does not cancel tools. Explicit immediate insertion cancels handler waits; neither mode automatically replays tool work or guarantees external process termination.
- An inserted user message is appended to the conversation exactly once.
- Partial generated assistant output is retained and marked interrupted before the inserted user turn.
- Stale run IDs and terminal statuses cannot mutate a different run.
- Existing explicit `cancel` continues to mean cancel the entire stream.
- Idempotency is scoped to authenticated owner and command ID.

**Security model**: Control commands require the existing WebSocket token, agent access check, and an owned thread matching both agent and authenticated user. No command may target a Bridge/remote thread by spoofing its ID.

**Critical test scenarios**:

- Queue 2 messages, refresh/reconnect, observe original FIFO order, withdraw the second before dispatch: verifies **AC-1**, **AC-2**.
- Request run-now during model generation with partial tokens, then verify interrupted assistant text, one user insertion, and resumed stream: verifies **AC-4**, **AC-7**.
- Request run-now before/after a tool and while a side-effecting fake tool is blocked; confirm stale tool call does not start and an already-running tool executes once: verifies **AC-5**, **AC-6**.
- Replay command ID, use stale run ID, and attempt another owner's thread: verify no duplicate or unauthorized mutation: verifies **AC-2**, **AC-3**.
- Open HITL pause with a queued message: verify no queue flush starts until HITL completes: verifies **AC-8**.

## Build plan

1. Add the durable, idempotent server-side control/status service and WebSocket frames with ownership validation (**AC-1**, **AC-2**, **AC-3**).
2. Add Harness phase observation and cooperative LLM stop/resume while guarding tool transitions atomically (**AC-4**, **AC-5**, **AC-6**, **AC-7**).
3. Integrate gateway turn/history handling and phase-aware dashboard controls, preserving FIFO and HITL deferral (**AC-1**, **AC-4**–**AC-8**).
4. Add synthetic cross-layer regression coverage and run the app/Harness gates without touching production conversations (**AC-2**–**AC-9**).

## Migration plan

**Strategy**: Additive server APIs and receipts; ship the Dashboard and pinned Harness wheel together after integrated checks. A native run advertises runtime controls; unsupported transports keep their existing behavior.
**Rollback**: Revert the application/Harness dependency together, leaving receipts available for inspection. No existing chat history is rewritten. No schema migration is required.
**Evidence so far**: real-graph tests cover token interruption and checkpoint retention, stale tool prevention, once-only side effects, cancellation drainage and the final-model boundary. SQLite/gateway tests cover FIFO, capacity, retries, ownership, withdraw/dispatch races, recovery and persisted HITL pauses. Dashboard tests cover retry identity, acknowledgement under refresh failure and separated interrupted/user/new-answer bubbles. App 4921 tests and Harness 1846 tests passed. Final Dashboard target44 tests, TypeScript, ESLint for the final changed streaming files, and production build passed. Independent final review passed, including delayed2200-event streams. Twelve unrelated full-Dashboard failures were reproduced on the untouched baseline; see the implementation progress for evidence.

## References

- `dashboard/src/pages/Chat/hooks/useChatMessageQueue.ts`
- `src/octop/api/routers/chat/ws.py`
- `src/octop/infra/gateway/process/processor.py`
- `src/octop/infra/agents/manager.py`
- Harness `src/octop_harness/agent.py` and `src/octop_harness/protocols/langgraph.py`
- Existing `run_events` repository and table
