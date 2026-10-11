# Reference coverage and current delivery contract

References are read as product examples, not workspace instructions:

- Knowe-agent-groupchat: `src/components/Composer.tsx`, `ChatStream.tsx`, project/member UI.
- dsh-web dev/packages/dsh-task-board: `README.zh.md`, `src/core/verification.ts`,
  `src/host/verification-runner.ts`, task use cases and host ledger.

The user requires a usable Octop-based product, Windows/Linux first, Android via
the existing remote connection. Reuse Octop data, permissions and runtime. The
reference is a behavior contract, not a requirement to replace Octop with DSH.

## Navigation and group chat

One icon rail (64px), contextual navigation (232px), and flexible content pane.
Personalization categories appear once on desktop; mobile uses the tab bar. Long
headers wrap before their title is squeezed. No implementation instructions in
empty navigation areas.

Conversation rail has a new-group action; groups sort above private agents.
Project room header shows member avatars, live busy status, member management,
usage and board. Each member exposes @, private chat/history, configuration and
task/handovers. @ uses Octop's existing name tokens and ask_agent routing, which
must be verified against an actual member reply, not just a text chip. File drops
on the chat area use the existing authenticated upload path.
The host's read_group_attachment tool reads only its inbound attachments through
BackendWorkspace, with byte/text limits and pagination. It never grants general
filesystem access. Board tools resolve the gateway's authenticated configurable.user
field and reject a missing/invalid user instead of opening a zero-user ledger.

## Task board

- Five columns, deterministic tag color, project/member/search/tag intersection,
  subtasks hidden by default but visible when explicitly filtered or expanded.
- Host tag rename/remove affects active and archived cards. Optional tag prompt
  prefix is frozen into a confirmed execution. Editing it invalidates confirmation.
- AI parse uses a configured real model; cards edit execution/reviewer model,
  automatic or human acceptance, optional one repair, fresh/continued session.
- A single tree-run transaction preflights every pending descendant, claims them
  atomically, then runs under the host concurrency ceiling (8). Confirm tree,
  parent graph and cancellation use the same service. Parent completes only after
  its own accepted output and every child. A failed child prevents settlement.
- Progress, next step and handover snapshots are visible/editable; retained run
  records link to the actual Octop thread.
- Automatic acceptance reads actual harness history/tool evidence, redacts common
  credentials, caps the evidence and reports truncation. Six independent calls:
  three criteria, two swapped A/B rounds versus an empty-work baseline. Every
  mean score >=65 and total greater than baseline is required. Isolated judge
  messages have no executor tools. One optional repair and re-verification.
- Judge exceptions are recorded as anomalies; never an invented quality score.
  They hold completion pending an explicit retry or independent human report.
  Judge usage is added to the normal host usage ledger.
- Five-field cron/IANA timezone; Unix numeric weekdays and restricted DOM/DOW OR.
  Database ledger and scheduling survive closing the page. Restart interrupts an
  unknown live run, skips missed triggers and never silently repeats execution.
- Eight agent tools use the same owner checks, revision transaction and gates.

## Remaining differences requiring honest reporting

Octop uses its own agent sandbox and approval policies rather than DSH presets.
The reference's twenty-letter scoring scale is represented as validated numeric
scores. Interrupted runs are failed closed; reconnecting an in-flight remote
session after host restart is not implemented. Native sleep inhibition, GitHub
issue sync and reference extensions are not part of the user's requested slice.
Knowe's role-catalog employee picker and favorites/shared project memory are not
yet reproduced; existing Octop expert templates and memory are retained.

## Verification status

Windows portable preview rebuilt and browser-checked on 2026-10-08. Full backend
baseline: 4194 passed, 142 skipped, 35 deselected. After the last attachment and
authenticated-tool fixes, the affected suite passed 270 tests with one skip;
strict mypy (571 files), Ruff and frontend production build passed. Browser proof
includes real member replies, attachment text, model acceptance, parent/child
settlement, archive/restore, tag filtering and group lookup of the same board.
The archive view shows archived children without requiring the child toggle.
See verification.md for exact evidence, remaining UI checks and platform limits.
