# Collaboration resources review

Contract: docs/specs/0031-collaboration-resources/index.md, revision2026-10-18.4.
Review date: 2026-10-18, Asia/Shanghai.
Reviewer: independent GPT-6 Luna high, requested by the user. Coders: GPT-6.1 Sol high. Architect/integrator: root.
Baselines: application60111355 and Harness2ac4d602 plus the preserved interrupted dirty patches listed in ops/collaboration-development-20261018.md.

## Verdict

The final independent read only source pass found no remaining material findings. This is a source review verdict, not a statement that all runtime acceptance is complete. Application integration gates are recorded separately.

## Findings resolved

1. Concurrent same-callee invocations could share child session and prompt state. New invocations now have distinct child thread/session identities and stored relations.
2. Snapshot bytes and publication metadata needed crash ordering. Publication stages, verifies, flushes and atomically finalizes bytes before committing resource metadata/event; unreferenced bytes are not advertised.
3. Event cursor and cancellation transitions needed exact rules. The contract defines exclusive increasing scoped cursors and terminal transition guards. PostgreSQL event-producing transactions lock the root thread before allocating event sequence IDs.
4. Running coroutine cancellation was incorrectly treated as proof of remote cancellation. The canonical awaited cancellation API first persists the request; definitely unstarted work can be cancelled, entered execution without underlying acknowledgement remains unknown.
5. Completion winning a cancellation race lacked a too-late record. Current state and a distinct idempotent delegation.cancel_too_late event now commit together while preserving completion.
6. Identical publications from different tasks/devices could collapse provenance. Resource reference identity now includes publication thread/invocation and source device/context; owner-scoped snapshot bytes still share a digest.
7. Root integration also found stored human/ai roles incompatible with the frontend's user/assistant filters, now normalized in the public detail API. Raw tool/reasoning bodies are excluded.
8. Full frontend testing found eager resource preview imports loading the PDF engine in unrelated docks. The actual dock boundary now lazy loads resource preview, and the previously failing add-tab suite passes without test-only globals.

The reviewer withdrew a provisional version-loss concern after confirming resource_id names a single immutable digest/provenance reference, rather than a mutable latest-version resource.

The final correction pass also inspected verified startup unavailable/recovery transitions, configured upload-size versus parser-size bounds, both actual Processor model-input paths, latest-500 snapshots plus owner/thread event-reference lookup, indexed run/status queries, and safe localized UI reasons. No remaining material finding was reported. A provisional concern that registered uploads would be rendered as unavailable artifacts was withdrawn: the actual panel filters both upload sources and registered state before its artifact rendering loop. No source change was necessary for that concern.

## Scope inspected

Harness actual tool schemas/ToolRuntime injection, invocation identity/replay, awaited acceptance/cancellation and inbox behavior; application lifecycle/resource repositories and services, upload/thread registration, grants and parent result access, HTTP ownership and public message projection; frontend actual chat/dock mounting, cursor merge and verified resource preview/download.

## Limits

The reviewer did not execute tests. PostgreSQL ordering and migration behavior were reviewed statically; no live PostgreSQL environment was available. Browser automation explicitly reported that local browser use is disabled in Work settings, so no live visual acceptance is claimed. Component journeys and builds are implementation-team evidence and are recorded in the final verification record.

No source commit, push, production deployment or live memory mutation occurred during this review.
