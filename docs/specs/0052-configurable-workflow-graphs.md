# Agent-configurable workflow graphs

**Status**: Accepted
**Date**: 2026-11-10
**Mode**: FEATURE
**Confirmed**: User accepted the full specification and independent cross-check. Follow-up decisions: budget exhaustion pauses successors and retains accepted Jobs; script events can start new runs as well as signal waiting runs.

## Summary

The user wants Agent-owned procedures that run without constant manual follow-up. The confirmed design is a generic graph for code execution, evaluation, analysis, improvement and daily work. Both the user and Agent author the same graph, including a full visual drag/drop editor. This replaces the earlier GPU-specific research-scheduler direction.

Each node has explicit input/output state and before/after conversation context. The user confirmed that “window” means an Agent conversation, not an OS/browser window. Nodes can use the current conversation, start an independent conversation, or adjust model context while keeping the current conversation. Adjustments can be temporary or inherited by later nodes. The complete chat archive remains available.

## Requirements

- AC-1: Users and Agent tools create, read, update, validate, publish and archive owner-scoped graphs through one service. Concurrent edits use revision checks. Running instances retain their immutable published definition.
- AC-2: The visual editor supports adding, dragging, connecting, inspecting, deleting and configuring nodes/edges; zoom/pan/fit; undo/redo; validation errors; saving and publishing; starting, inspecting, pausing, resuming and cancelling runs. Import/export preserves the same validated definition. Use the existing dashboard visual language and theme.
- AC-3: Nodes include entry, Agent, script/command, condition, event registration, event wait, timer wait, fork, join and end. Conditions use a bounded declarative comparison, never eval. Loops are allowed within explicit run step/time limits. Independent runs and fork branches may progress concurrently, subject to conversation locks and a bounded worker capacity.
- AC-4: Manual starts, scheduled starts and script-produced events use durable records and idempotency. Waiting for an event/time/Job does not occupy a model turn. Early events remain available until the wait node consumes them. Daily schedules use the configured timezone and do not replay an unbounded missed backlog.
- AC-5: Agent nodes reuse CronDeliveryService and the existing harness request/model-routing/history path. Scripts use persistent Jobs and the frozen execution source. Actual receipts determine completion. An observation failure never restarts an accepted experiment.
- AC-6: Before-context chooses current/new conversation, history inheritance or a recent-turn/empty projection, explicit injected context and input mappings. After-context chooses whether subsequent nodes retain or restore the incoming conversation/context and which output variables they receive. New conversations remain separately inspectable and linked to the run. Graph context changes do not delete history or broaden authority.
- AC-7: Each activation stores its effective input, output, conversation, context recipe before/after, timestamps and actual state. The editor highlights the active/waiting/failed node and allows inspection of prior activations, including loops.
- AC-8: Restart recovers durable waiting and queued work. Model/command admission uses persisted claims; uncertain in-flight work is surfaced rather than silently replayed. Cancellation stops further dispatch, cancels owned Jobs when requested, and reports accepted in-flight analysis honestly. Deleted/revoked origins are blocked, never redirected.
- AC-9: A script can receive a scoped callback URL/token through its environment. Event data is bounded untrusted JSON, cannot alter graph definitions, execution targets or conversation authority. Retried callbacks are deduplicated. Secrets are not included in normal run-state responses.

## Decision

Reuse Python/FastAPI, the current database pool and paired SQLite/PostgreSQL migrations, existing durable Jobs, wakeup-hook authentication and CronDeliveryService. Store definitions and activations in the control plane, separately from model checkpoint/history storage. Use an owner-scoped declarative schema, not arbitrary executable graph code.

The editor uses React, Ant Design, Lucide and a native SVG/DOM canvas, matching the installed dashboard stack. Nodes, handles and edges remain DOM-accessible. No new frontend dependency is required. A dedicated graph library was considered; reusing the present stack avoids changing shared dependencies while preserving the requested authoring interactions.

**Implementation skills**: develop, frontend-design, test/debug as needed, check verify/review and sync.

## Context

Existing Jobs and hooks can run work and deliver a one-time callback. The missing user-facing capability is a durable, editable procedure that routes results into further work and declares which conversation/context each step uses. The user explicitly requested a generic mechanism and a complete visual editor, replacing the earlier GPU-specific direction.

## Options considered

1. Extend prompts and individual callbacks only. Smallest change, but procedure state, graph authoring and context transitions remain implicit.
2. Versioned declarative Graph using existing execution and delivery (selected). Adds explicit procedure state and the requested shared UI/tool authoring surface, while retaining established execution policies. Costs new schema, scheduler and editor work.
3. Introduce an external workflow engine and graph UI dependency. Mature orchestration options, but adds deployment and adapter contracts absent from this self-hosted stack.

## Feature design

### Workspace layout

The user refined the layout after reviewing the working editor. The Graph workspace fills the available viewport with no page hero or outer card padding. The compact header contains the Graph picker, name/version state and one workflow-settings entry. Save, publish, start, import/export, undo/redo, validation and management actions belong in that settings Drawer. The Graph library is a separate picker Drawer. Node creation uses a floating popover, the node inspector opens only on selection, and run history starts collapsed. Node cards use semantic icons/colors, task previews and concise context chips with visible input/output ports.

Advanced JSON is normalized against the server schema before installation. Async validation must discard results after a Graph/node switch, newer edits or inspector closure.

### Data model

| Entity | Stored fields and constraints |
| --- | --- |
| Graph | Owner + graph ID, name, current revision, draft definition, published revision, archived timestamp, created/updated time, schedule next due time. Owner/ID is unique. |
| Graph version | Owner, graph ID, revision, immutable validated definition and creation time. Composite FK to graph, unique version. |
| Graph run | ID, owner, graph ID/version, state, request idempotency key, initial/current variables, origin expert/thread/execution context, step/time budgets, timestamps, error and pause/cancel intent. Published version is immutable. |
| Node activation | ID, run, node ID, ordinal, status, branch token/parent activation, effective input/output, before/after context, conversation ID, external Job/hook link, error/times, worker claim/lease. Multiple visits to a node have distinct activation IDs. |

Definitions contain at most 64 nodes and 128 edges. Node IDs are unique. Entry is unique; referenced nodes and ports exist. Non-fork nodes route at most one edge per outcome. Fork/join pairs are explicit; branch outputs are namespaced by producer activation. Shared-variable assignment is explicit and transactional. An undefined binding or malformed result is an execution error, not an empty success.

Node types and their configuration:

| Kind | Named inputs | Result |
| --- | --- | --- |
| entry/end | Initial state or optional selected result binding | Start/terminal receipt |
| agent | Owner-visible expert ID, prompt, optional usable model ref, context policy, bindings | Recorded answer, thread and request/run references |
| script | argv list, working directory/source context, env bindings, optional registered callback node | Durable Job reference, terminal receipt and bounded output |
| condition | State binding, operator, comparison value | true/false outcome |
| event | Event type, purpose and expiry | Scoped single-use signal-hook reference and callback URL |
| wait_event | Binding to a registered event node | Actual received event data |
| wait_time | Duration seconds | Persisted wake deadline |
| fork/join | Explicit paired node ID and outgoing branches | Branch tokens and deterministic join completion |

Context policy:

- Before session: `current` uses the incoming branch thread, `new` creates a child thread for the selected expert. A current session must belong to the selected expert and owner.
- Before history: `inherit`, `recent` (1..100 recent user turns), or `empty` (current task turn only). Always preserve protected system instructions and complete tool-call/result sequences. Extra context comes only from the node's configured literal or resolved input bindings.
- After session: `keep` passes the effective thread to successors, `restore` passes the incoming thread. The child thread and its result remain recorded either way.
- After context: `keep` passes the effective projection recipe to successors; `restore` reinstates the incoming recipe. This is a Graph-runtime projection, not destruction of checkpoint or archive messages. An ordinary manual chat does not inherit a Graph-only filter.
- Output assignment maps named node output fields to graph variables. Inputs resolve explicit JSON paths in initial variables, prior activation outputs or received event data. No expression evaluation or implicit filesystem reads.

Runs default to 100 node activations and one day of wall time, configurable within 1..1000 activations and 60 seconds..30 days. These are workflow limits, not fabricated GPU billing quotas. Queued work is globally bounded. Model dispatch has a bounded timeout and a persisted lease; normal waits are durable rows. A fork carries a group/branch token; join consumes one arrival from each branch in that group before continuing.

Worker defaults are four globally active node dispatches, with at most four per owner; model nodes time out after 600 seconds unless configured within 10..3600 seconds. Claims last 120 seconds and active workers renew every 20 seconds. Expired uncertain dispatches become unknown. Ready/waiting work is examined in bounded batches. State and result previews have explicit size limits, while large outputs remain device/history references. Fork output namespaces and explicit join mappings resolve parallel results; conflicting concurrent shared-variable writes fail visibly instead of silently overwriting.

### State transitions

Graph: draft revisions → published immutable revision → later draft/published revisions; archive disables new scheduled starts.

Run: queued → running ↔ waiting → succeeded/failed; pause blocks new admission, resume continues queued/waiting work. Cancellation prevents new node dispatch. Uncertain interrupted side effects are `unknown` and require an explicit retry/reconciliation decision.

Activation: ready → running → completed/failed, or running → waiting_job/waiting_event/waiting_time → completed. Claims use compare-and-swap. Accepted work is never inferred successful from a callback alone.

### API and tools

Owner-authenticated API at `/api/workflow-graphs`: paginated list; read graph/version; revision-checked upsert; validate; publish; archive; idempotent start; paginated run list; run detail with activations; pause/resume/cancel. Runtime control uses typed request/response models and the same service as Agent tools.

Agent tools: `workflow_graph_list`, `workflow_graph_get`, `workflow_graph_save`, `workflow_graph_validate`, `workflow_graph_publish`, `workflow_graph_start`, `workflow_graph_run_status`, `workflow_graph_control`. Their acting owner/expert/thread comes from trusted runtime config. Saving a draft does not modify running instances. Explicit start/publish is a separate action.

Events reuse the scoped `/api/wakeup-hooks/{hook_id}/fire` route, adding an internal signal-only delivery mode that persists arbitrary bounded data without independently invoking an Agent. The Graph event wait consumes that signal exactly once. Looping through the event-registration node creates a fresh scoped hook for that activation.

### Value sourcing

| Value | Source |
| --- | --- |
| Actor/visibility/permissions | Existing authenticated user and owner-scoped expert/thread/device services |
| Definition, positions, edges, context policy | Validated Graph draft saved by UI or Agent tool |
| Active definition | Published version pinned at run creation |
| Initial state, start idempotency key, origin | Start API/tool inputs with owner checks; saved definition for scheduled starts |
| Node input / condition values | Explicit bindings into persisted run state and prior outputs |
| Script/model outcome | Existing execution receipt or CronDeliveryService result, not callback assertions |
| Callback data | Authenticated single-use hook payload, retained as untrusted event data |
| Context before/after / conversation | Effective branch token, node policy, actual created/resolved thread and request projection |
| Run/node state and visual highlights | Durable repository records and actual receipts |
| Schedule timezone | Definition input, defaulting to the existing server timezone |
| Limits | Validated definition/start settings with the bounded defaults above |

### Failure and authorization rules

Every graph/version/run/activation lookup is owner-scoped. Agent, thread and execution context are revalidated at dispatch. Model overrides use existing usable-model validation. A new child session grants no additional tools or target access. Event data never selects an expert, model, work mode, graph revision, thread or device.

No node action uses `eval`, executes unvalidated expression text, or bypasses RequestExecutionBackend/ExecutionService. Accepted Jobs retain deterministic idempotency and original context. Leases prevent simultaneous dispatch; expiration of an uncertain running action surfaces `unknown`, while ordinary waiting recovers automatically. Stop and pause behavior is visible in run records. Callback tokens are derived from the existing secret and provided only through an owner-authorized callback view or execution environment, not public run inspection.

## Build plan

- [x] Implement validated definition, binding and context schemas, repository and paired migrations (AC-1,3,6,7,8).
- [x] Build the durable engine, Agent/script dispatch, signal/time/Job waits, conditions/loops, fork/join and schedule recovery (AC-3,4,5,8,9).
- [x] Integrate Graph-only model context projection and child/current conversation routing (AC-5,6,7).
- [x] Expose typed owner-scoped API and Agent authoring/control tools (AC-1,4,9).
- [x] Build full canvas/editor, node/context inspector, version actions and run timeline/state inspection (AC-2,6,7).
- [x] Add example daily and event/iteration flows, verify interactions and state transitions through focused tests and real canvas checks, run relevant gates and independent review (all ACs). See `docs/workflow-graphs-validation.md` for evidence and validation limits.

## Critical test scenarios

- Revision conflicts and cross-owner access cannot modify or reveal another graph/run. Publishing a new revision leaves an active run on its original version (AC-1).
- Agent tools and drag/drop editor produce the same canonical definition; malformed links and unbounded cycles are rejected or bounded at runtime (AC-1,2,3).
- Script completion comes from a Job receipt, early signal data is retained, callback retry is deduplicated, and a wait resumes after restart without submitting the Job again (AC-4,5,8,9).
- Parallel branches join once per fork activation; a loop creates fresh activations and honors step/time limits (AC-3,7).
- Current/new sessions preserve owner/expert constraints. Temporary context restores for successors; retained context passes forward. Protected system messages and tool-call/result integrity survive trimming. Full archives remain intact (AC-6,7).
- Pausing prevents new dispatch while retaining truthful in-flight state; cancellation and expired leases do not falsely report successful completion or silently repeat uncertain effects (AC-8).
- A daily trigger uses its saved timezone and cannot create duplicate runs during concurrent ticks or restart recovery (AC-4).

## Independent cross-check resolutions

The independent review identified seven missing behavioral contracts. They are resolved here before implementation.

1. Binding grammar is `$.vars.<key>`, `$.outputs.<node>.<field>`, or `$.event.<field>`, with object keys and numeric array indexes, no executable expressions. A binding explicitly selects a literal or path. Each branch carries a variable snapshot and a latest-completed-output map for its own lineage. Loop visits replace that lineage's node-output pointer; every actual activation remains separately stored. Cross-branch reads happen only at joins. Agent/script outputs have a canonical `text`, optional parsed `result`, and evidence references (`thread_id`/`job_id`); JSON mode must parse one complete bounded JSON value or fail.
2. Fork regions are structured and paired. Every branch must reach its matching join, with no cross-region jumps. A branch failure or unknown state blocks new sibling dispatch and the join; already accepted work remains observable. Joins restore the pre-fork conversation/context by default or explicitly select a named branch. Explicit branch-keyed merge mappings combine outputs; conflicting assignments fail instead of last-writer-wins. Loops inside a branch retain the fork token until that branch joins.
3. An Agent activation enters the existing conversation request lock used by cron/chat for the same expert/thread, not a Graph-only parallel lock. Waiting for a busy conversation stays queued and does not consume active-dispatch capacity. A context recipe is portable: `recent` is recalculated at each activation; injected context replaces rather than accumulates. Therefore restoring the parent session while retaining a recipe applies that recipe to the parent's history, without importing the child's transcript. A new-session node targeting a different expert must not reuse the old thread.
4. Schedule input is a five-field cron string plus IANA timezone, saved initial variables and saved expert/thread/execution source. Timezone defaults to server config, DST follows the existing APScheduler trigger contract. Missed occurrences are skipped on restart, consistent with the current task board; there is no replay backlog. Default overlap policy is skip while an instance is active; a definition can explicitly allow parallel starts within queue limits. Publishing controls future ticks and pins the current published revision at admission; archive disables future admission.
5. Visible states include pausing/paused, cancelling/cancelled and unknown. Pause prevents new admission and does not fabricate cancellation of accepted work. Budget exhaustion follows the user's chosen pause-and-retain policy. Accepted Jobs can be reconciled by receipt observation without resubmission. Unknown work can be explicitly authorized for a new activation attempt only by the owner; this is a separate control action from observing the accepted operation. Model timeout or lost lease with uncertain effects records unknown. Claims have dispatch identities and receiver-side Job idempotency; a lost lease cannot authorize a late new dispatch.
6. Signal hooks retain the existing 8192-byte JSON-data and 12288-byte request bounds, event-type checks, authenticated retry/deduplication and 60-second..30-day expiry. An event-registration activation has one consuming wait; multiple static consumers are rejected. Expiry without a received signal fails the wait. Early received data remains consumable even after its original delivery deadline. Separately, a published Graph exposes an owner-authorized, revocable Graph-scoped HMAC event-start capability: event ID and bounded data create an idempotent run on the latest published revision. Equal retries return the original run; same ID with different data conflicts. It checks live origin and graph state before admission. Capability rotation/archive invalidates further starts. Run inspection does not expose callback tokens.
7. Bounds: 32 queued runs per owner, 128 globally; initial variables 64 KiB, branch/run state 512 KiB, activation input 64 KiB, output preview 32 KiB, injected context 32 KiB, callback data 8 KiB. Oversized structured data is rejected; text previews may truncate only with explicit truncation/evidence metadata. Four active model requests or accepted Graph Jobs globally (and at most four per owner) count until their operation actually ends; signal/time waits consume no such capacity. Ready admission rotates owners, skips busy conversations, and prioritizes finishing accepted work over new submission. All byte limits use UTF-8 encoded JSON/text.

Accessible canvas authoring includes focusable node/port controls, a keyboard connection action, selection and deletion, and undo transactions. These interactions must be demonstrated alongside pointer dragging and zoom/pan before the editor is considered complete.

## Consequences

Graph definitions are portable declarative data; script/model capabilities remain those already authorized by the platform. New storage is paired for SQLite/PostgreSQL. Runtime context projection is separate from durable chat history. No GPU-specific fields or new external services are needed. Existing single-use wakeup behavior remains the default for callers outside Graph signal nodes.

## Rationale

Existing durable Jobs, conversation-scoped event hooks and cron delivery supply execution and wakeup primitives. A versioned Graph adds the missing durable procedure and explicit context/state boundary. This avoids coupling general automation to experimental metrics or a particular GPU scheduler.
