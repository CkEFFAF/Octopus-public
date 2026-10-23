# Background tasks, free channels and overview refinement

Implementation complete on fix/background-tasks-free-channels, based on d92a8525.
PR #50 merged as cd0e3a28 after Linux CI, builds and CodeQL passed. Production
activated that source with a full private backup and preserved existing resources.
Final configuration verification found the Free Models Hub route duplicated its
provider mount prefix; a follow-up release is required for that entry point.

1. Metadata: same-model bounded format repair, compact output, truncation
   detection, safe copied diagnostics (field paths/types, HTTP/request/retry
   metadata). Chat diagnostics also survive history reload. No raw prompts,
   provider bodies or validation inputs are persisted in these diagnostics.
2. Stop: account batches and individual jobs revoke leases; in-flight calls
   cancel within the polling interval and late completions cannot commit.
   Polling responses from before a stop cannot restore stale running UI.
3. Background: persisted job observations and running schedules join real turn
   activity. Stale job observations are explicit; owner/expert boundaries apply.
4. Expert panel: active conversations/background jobs plus existing schedule and
   reminder tabs, opened in place with unchanged chat selection.
5. Pinned experts: both sidebar variants open and scroll the selected group,
   including repeat selection. Unit regression asserts scroll behavior.
6. Channels: full standalone discovery with explicit enable-all; Zen anonymous
   free-only preset; Free Models Hub public directory and key-signup/setup UI.
7. Artifacts: shared filesystem icons, expanded common scientific/document/media
   types, bounded square cards and ellipsis/full-path access.
8. SessionGraph study: upstream cd1f0705 inspected. Original structured outline
   projects existing brief/source refs, standard/compact modes, Markdown/Mermaid/
   pending-TODO exports. No second model call or upstream runtime installation.

Evidence:
- make all PYTEST_JOBS=8: 5122 passed / 157 skipped, strict mypy 691 sources,
  Ruff green. Log tasks-channels-make-final.log.
  Final discovery review added a free-only guard to the ordinary Zen fetch-models
  action; its directory/probe regression group passed 17 tests after that change.
- Full Vitest: 289 files / 1572 tests passed, TypeScript green. Final minor
  responsive drawer and callback changes: overview/settings/free-channel group
  8 passed. Logs tasks-channels-vitest-final.log and tasks-channels-last-ui.log.
- Actual local app (isolated synthetic account): long filenames clipped inside
  162px square cards, notebook/weights/office icons observed; structure outline
  19 nodes and copy/export controls visible. Pin click scrolled sidebar to
  1059px and expert task dialog retained the chat URL, summary tabs visible.
  An actual 62-thread history batch stopped with queued=0/running=0 and 56
  cancelled; completed work remained. Browser space15 was finished once after
  this check. Transition overlays blocked some native pointer calls, so the
  documented DOM-action fallback was used for the final stop and pin checks.
- Browser emulation/compositor did not synchronize mobile layout with its
  reported 375px viewport; no reliable mobile visual claim is made. Drawer width
  now uses CSS min(600px, 100vw), with no viewport-hook dependency.
- Screenshot API was unreliable in the preceding run; this pass uses DOM,
  interaction and computed-style evidence.

External limits (2026-10-23 fictional-only probes): standalone lists 26 entries;
several tested models return 429, with Free usage limit reached. Direct Zen
returns 403 FreeTierError. Directory membership is not a working-call claim.
Free Models Hub currently returns 9 channel entries; keys require user signup.
No real chat text sent to new provider smoke tests and no paid fallback used.

Release follow-up: the actual /api/providers/free-hub integration test reproduced
404 before the one-line route correction, then provider API/catalog tests passed
(12 tests). The regression checks the dashboard path through build_app and its
authentication boundary. Final commit/PR/deployment checks remain in progress.
