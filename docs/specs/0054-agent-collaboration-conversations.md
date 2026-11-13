# Agent collaboration conversations

**Date**: 2026-11-12
**Status**: In Progress

## Summary

Show local Agent to expert communication and outbound ACP communication under a separate Agent collaboration tab. Display the actual authenticated actor, such as Codex, and keep the human owner's ordinary conversations separate. Persist the transcript and source links so refresh and later inspection retain the same identity.

## Requirements

1. AC1: A machine credential creates an independent collaboration conversation and shows its server registered name. Client supplied text, titles, headers or sender objects cannot impersonate Codex or the owner.
2. AC2: Ordinary user conversations and Agent collaboration have distinct sidebar tabs. Pagination, heat ordering and active session shortcuts respect the selected category. Opening a deep link selects the correct tab.
3. AC3: Historical and live messages carry a trusted optional sender. External machine input shows the machine actor rather than the logged in human. Genuine later human replies remain human.
4. AC4: Each actual outbound ACP session has a durable collaboration transcript with the expert and runner identities, real prompt, responses and errors. It links to its parent expert conversation. The parent retains the permission controls and a child conversation link.
5. AC5: Continue using direct oaa_ credentials and the existing work item surface for machine input. Do not exchange a machine key for a user JWT or expand the machine route whitelist. Preserve owner, expert allowlist, resource grant and device execution boundaries.
6. AC6: Credentials and private environment values never enter conversation metadata or output. Revocation does not destroy the historical actor snapshot. Tests prove forged sender rejection, both history and live serialization, category pagination and ACP failure or permission states.

## Decision

Extend existing machine principal, sessions and HistoryArchive in place. No new queue, database column or authentication mechanism is required. The screenshots are visual references for named participants and source badges, not authority to alter existing permission boundaries.

The existing sessions.channel_metadata owns category, actor snapshot and collaboration_source. Existing source strings retain their old meaning. Machine actor identity comes from the authenticated credential ID and its server stored key name. Work item creation and each authenticated input retain their own actor in trusted event data, which the worker projects into session metadata and HumanMessage.additional_kwargs. User body fields never decide that identity.

Public thread and sidebar entries expose category (user or agent_collaboration), optional actor (kind/id/name), and optional collaboration_source (kind, parent_thread_id, runner_name, acp_session_id, device_id). Message serialization exposes sender with the same actor shape when an authenticated nonhuman source exists. Missing data defaults to ordinary user semantics, not a title based inference.

Outbound ACP is captured in the application RequestACPService around its real structured run_turn, session, permission and result lifecycle. A unique collaboration session is keyed by the actual ACP session ID, owner, expert and device. Its initiating sender is the expert; its responding sender is the configured ACP runner. HistoryArchive begin/save_messages/finish writes the v2 readable history. An error or permission request remains that state and is never fabricated as a successful reply. No Harness fork is required for this part.

## Value sourcing

| Value | Source |
| --- | --- |
| Machine actor ID and name | Authenticated MachinePrincipal credential and stored agent_access_keys.name |
| Owner and allowed expert | Existing credential owner, scopes and expert allowlist |
| Work item input actor | Server authenticated create/input request event, never payload sender |
| Category and historical source | sessions.channel_metadata snapshot |
| ACP participant and session | RequestACPService runner configuration and actual session handshake |
| ACP parent and device | Persisted authenticated ExecutionContext and current expert invocation |
| Message sender | Trusted additional_kwargs projected by backend serialization and live echo |
| Category selection | User selected sidebar tab or the category of a deep linked session |

## Build plan

1. Persist and project authenticated machine actors through work item and direct machine session paths (AC1, AC3, AC5).
2. Capture actual ACP sessions in separate HistoryArchive threads with source links (AC4, AC5).
3. Filter thread listing before limit and expose metadata on working sidebar entries (AC2).
4. Add the collaboration tab, participant identity and source links across history and live messages (AC2, AC3, AC4).
5. Run focused identity, authorization, history, UI and protocol regressions, then Linux make all and dashboard build (AC6). Use only DeepSeek for any live model validation under the current owner budget instruction. A provider limit is a blocked live check, not a passing one.

## Consequences

Old owner authenticated messages are not retrospectively relabeled as Codex. A historical source may be projected only when the stored machine session or work item event proves it. Existing accepted GPU Jobs and ordinary conversations remain intact.
