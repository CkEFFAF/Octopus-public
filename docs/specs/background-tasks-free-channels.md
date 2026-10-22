# Task visibility, cancellable metadata and free model channels

Status: Complete (implementation checked; release tracked in progress record)

User-authorized continuation of the deployed provider/UI fixes. This enhancement
uses the architect and debug workflows; existing account/provider boundaries apply.

- AC1: Experts and sessions distinguish configured background schedules from
  currently running work, with counts and reduced-motion-aware running indicators.
  An expert task panel summarizes active conversations plus schedules/reminders.
- AC2: Pinned expert selection opens and scrolls the corresponding sidebar group
  into view, including when already selected; ordinary polling must not move it.
- AC3: Account history batches and individual metadata jobs can be cancelled.
  Cancellation revokes leases so late results cannot write; in-flight requests
  stop, completed metadata remains. Disabling automation cancels automatic jobs.
- AC4: Metadata output is validated before storage. A single bounded format-only
  retry uses the same model and original sources; invalid references remain
  rejected. Diagnose with safe field paths/categories, never original chat text.
- AC5: Artifact cards reuse fileTreeIcon and extend common document/research/media
  types. Long filenames stay inside square cards; full paths remain accessible.
- AC6: Our Free Model exposes its entire live free directory, including untested
  entries. Never equate a listed model with successful generation; never fall back
  to paid models. Preserve user overrides during ordinary refreshes.
- AC7: Integrate dsh-free-models-hub as a public paginated catalog and explicit
  custom-provider setup with publisher signup links; keys go only into account
  provider storage. Integrate opencode2dsh's anonymous Zen lane as a distinct
  OpenAI-compatible provider with live free-only discovery. No DSH runtime/plugin
  installation, proxy rotation, quota/region bypass, or hidden paid fallback.

Design: reuse SQLite job status/lease cancellation (no schema migration), existing
schedule browser and shared file icon map. New fixed public catalog sources use
the existing last-good cache and source status UI. Third-party directory entries
are untrusted; display as text, validate HTTPS URLs and provider import explicitly.
Keys are never sent to the leaderboard. Zen availability is checked on this host;
an upstream refusal remains visible and is not represented as working.

Build/verify: regression tests for leases, cancellation, format retry and ownership;
UI tests for task summary, pinned positioning, cards and free catalog setup;
fictional provider smoke, real app checks, make all, frontend build, then release.

Sources inspected: FishBottle7/opencode2dsh @89f7c420 and
yu-wenchao/dsh-free-models-hub @3c98fc5d; upstream code supplies wire contracts.

AC8 (user addition): study lwklbb/DSH-SessionGraph @cd1f0705 and extend the
overview with a source-backed structured outline (standard/compact modes) and
Markdown, Mermaid mindmap and TODO exports. Reuse existing validated metadata,
manual corrections and source inspection; no second summarizer or model calls.
Keep reported work distinct from verification and acceptance. Export TODOs only
from pending actions. Escape diagram labels and preserve source references.
The implementation is original; no upstream source is copied or installed.
