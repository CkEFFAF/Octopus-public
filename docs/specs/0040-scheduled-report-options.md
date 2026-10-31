# 0040. Scheduled report options

**Date**: 2026-10-31
**Status**: In Progress

## Summary

Add a daily report type to scheduled tasks. Let each task choose where reports appear and whether a new report receives a previous report as context. Existing tasks keep their current behavior.

## Context

Scheduled tasks currently use the same thread for visible history and model context. The `fresh_thread` option resets the bound thread before a run. A task without an explicit session uses the expert's dashboard session. This can create many visible chats or mix reports with ordinary conversations.

The user needs these choices to be independent. A report may appear in one continuing conversation while its generation starts without previous reports. A new visible conversation may also receive a previous report for comparison.

## Requirements

**User story**: As a task owner, I can choose the report conversation and the previous report context independently.

**Acceptance criteria**:

- **AC-1**: A scheduled agent task can be configured as a daily report. Its schedule remains editable using the existing scheduler.
- **AC-2**: A daily report can use one dedicated conversation per task or a new visible conversation per run.
- **AC-3**: Each run can independently omit previous reports or receive a configurable number of latest successful reports for the same task. Both the user and an authorized expert can set the number. The default is one, and the selection works in either conversation mode.
- **AC-4**: When previous reports are disabled, no previous report or other user conversation is supplied as conversation history to the report generation run.
- **AC-5**: Existing scheduled tasks and self reminders retain their current routing, context and schedules. No old conversation is deleted or silently merged.
- **AC-6**: A failed or cancelled run does not replace the latest successful report. Runs are serialized per task, and users cannot access another owner's reports.
- **AC-7**: The report is visible in the chosen conversation with its execution time and an accessible execution status. Existing delivery and notification behavior continues to work.

## Options considered

### Reuse the current thread switch

Keep `fresh_thread` as the only setting. This is small and already available. It cannot separate visible conversation history from model context, and a default session can be shared with ordinary chat.

### Separate report display and execution context

Keep a dedicated report conversation per task when selected. Run each report with its own context and explicitly include the selected number of successful reports only when requested. This supports all four combinations and isolates reports, at the cost of maintaining a report result record and managing temporary execution state.

### Create a full report management product

Add a separate report center and archive interface. It offers more navigation options, but it is a larger change than needed for the current request.

## Decision

**Chosen option**: Separate report display and execution context. Reuse the existing scheduler, task ownership, delivery and authorization mechanisms. Present the two choices as separate controls.

## Rationale

The existing switch controls both the visible conversation and the model checkpoint. The requested combinations require those lifetimes to be independent. A task specific destination also prevents one job from resetting or mixing another conversation.

## Feature design

**Data model sketch**:

- Extend the scheduled task configuration with a daily report designation, a conversation mode, a previous report context switch and a previous report count. The count defaults to one and accepts integers from one through 30. Existing rows remain ordinary tasks with unchanged values. Preserve self reminder metadata and semantics.
- Give each daily report task its own stable dashboard session key, derived from its task identity and owner. Keep the actual visible thread selected by its conversation mode.
- Persist each completed report's full visible output, owner, agent, task, attempt, visible thread and creation time. Enforce a unique attempt identity and an owner scoped lookup for the latest successful result. Do not treat the existing 2,000 character attempt excerpt as a complete report.
- Keep report execution checkpoints separate from the visible conversation. Each execution has an owner scoped thread with channel type `cron_internal`, excluded from conversation lists, search and organization views. Keep that row for execution and job evidence. Persist the transcript before checkpoint deletion. Durable attempt cleanup state is retried after runs, before the next run and every ten minutes, including after task deletion or process recovery.

**API surface**:

| Surface | Method | Inputs and outputs | Authorization |
|---|---|---|---|
| Existing agent cron collection | POST | Existing task fields plus report options; returns effective settings | Existing expert ownership rules |
| Existing agent cron item | PATCH | Partial report option updates; returns effective settings | Existing expert ownership rules |
| Existing agent cron list and detail | GET | Return the report type and both options | Existing expert ownership rules |
| Existing execution history | GET | Returns attempt status and its visible conversation | Existing task owner rules |
| Existing cron management tools | Tool call | Create and update the report options and previous report count | Existing authenticated expert and task owner rules |

**Value sourcing**:

| Value | Source |
|---|---|
| Report owner, expert and task | Authenticated task row |
| Display destination | Task conversation mode and its dedicated session binding |
| Prior reports | The selected number of most recent successfully persisted outputs for the same owner and task, ordered from oldest to newest before inclusion |
| Report time | Existing server timezone and attempt completion time |
| Execution status | Existing durable cron attempt |

**Key invariants**:

- The two options are independent. An isolated run never inherits the display thread checkpoint, including when it appends its result to that thread.
- Reference mode supplies report content as prior context, not arbitrary chat history or tool transcripts. If fewer successful reports exist than requested, use the available successes. If no previous success exists, the run starts without them.
- Report settings disclose that normal model context compression may summarize lengthy previous reports. Provider context errors surface as failed attempts; the application must not claim that compressed context was compared verbatim.
- A successful report is associated with one attempt. Retries cannot insert the same result twice. An interrupted run is not treated as successful.
- Reuse the existing session lock and add task serialization where needed. Never reset the expert's shared default session for a daily report.
- Carry any explicitly selected device, directory and execution mode into a new visible conversation and its internal execution thread, with the existing authorization checks.
- If a report is created from an IM session, also deliver its completed result to that original session after validating its current owner and expert.

**Security model**: The authenticated owner may configure and view only tasks and report outputs permitted by existing expert ownership rules. The previous report lookup is scoped by owner, expert and task. Scheduled report context must not expose unrelated user or expert conversations.

**Critical test scenarios**:

- Exercise all four combinations across at least two consecutive runs, checking visible conversations and the actual model inputs, verifies **AC-2**, **AC-3**, **AC-4** and **AC-7**.
- Exercise first run, a failed run, retry and concurrent triggers, verifies **AC-3** and **AC-6**.
- Create old style tasks and self reminders and verify their unchanged behavior, verifies **AC-5**.
- Attempt cross owner report access and history injection, verifies **AC-6**.
- Confirm live display, reload, execution history and notifications, verifies **AC-7**.

## Build plan

1. Add compatible persistence, API fields and expert tool parameters, with owner scoped result storage and task specific session identity, satisfies **AC-1**, **AC-3**, **AC-5** and **AC-6**.
2. Implement isolated execution and explicit previous report injection, then attach the durable output to the selected conversation, satisfies **AC-2**, **AC-3**, **AC-4**, **AC-6** and **AC-7**.
3. Add the daily report type and the two independent controls to the existing task editor. Explain their effects and preserve old task defaults, satisfies **AC-1**, **AC-2**, **AC-3** and **AC-5**.
4. Verify all four combinations, failure recovery and ownership in backend and dashboard tests, then verify the running application, satisfies **AC-1** through **AC-7**.

## Consequences

The conversation list stays manageable and the owner controls historical context. Dedicated result records and isolated execution state add storage and cleanup work. Existing reports remain in their original conversations unless the owner explicitly chooses a future migration.

## Migration plan

**Strategy**: Add the report mode alongside the existing task modes. Do not transform old tasks or old conversations.

**Phases**:

1. Add compatible storage and deploy code that continues to understand existing task rows.
2. Enable the new behavior only for tasks explicitly configured as daily reports. Verify both account isolation and all four option combinations before enabling a live task.

**Rollback**: Restore the previous application version. Existing tasks retain their prior fields and continue as before. Disable daily report tasks before rolling back because an older version does not implement their isolation semantics. Preserve the new data for later recovery.

**Risks**: A partial run can leave temporary execution state or a visible report without a durable result. The implementation must make this state recoverable and must not mark an incomplete attempt as successful.

## Follow-up

Existing reports created before report mode was enabled remain in their original conversations. Automatic consolidation and checkpoint retention policies are separate follow ups.
