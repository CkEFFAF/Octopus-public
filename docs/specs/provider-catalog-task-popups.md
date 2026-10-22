# Live provider catalogs, actionable metadata errors and task popups

Status: Complete (implementation verified; release tracked in progress record)

User-approved scope: update provider catalogs first, improve metadata errors second,
unify expert/session task previews and modal behavior third. Add the upstream
dsh-our-free-model project's OpenAI-compatible standalone provider.

## Acceptance criteria

- AC1: Models.dev supplies live metadata for existing supported provider presets.
  OpenCode Go's official model list determines current Go availability; discovery
  must never intersect it with an obsolete bundled ID allowlist.
- AC2: refresh on startup and at least daily; explicit refresh in Models settings;
  persist successful snapshots, preserve last good data on failure, expose source,
  last success, stale/failure state. Never transmit user keys to catalog services.
  Preserve explicit saved model settings and supported protocol boundaries.
- AC3: classify region denial, retired/unavailable model, authentication, quota,
  timeout and network errors without storing raw provider bodies/keys/prompts.
  Both per-conversation and batch UI expose useful reasons. No automatic switch
  to paid models. Smoke tests use fictional text only.
- AC4: add Our Free Model standalone provider with editable loopback OpenAI base
  (default http://127.0.0.1:18900/v1), its own key and live /models discovery. Do
  not treat its DSH plugin as an Octop plugin or bypass EAC host/auth restrictions.
  Pin/audit upstream source before running a separate standalone instance.
- AC5: expert/session previews share the existing white surface. Badge clicks
  open task dialogs in place, preserve chat URL/selection and correct scope;
  Escape/close work and refresh retains existing schedule features.
- AC6: organization settings use compact responsive model cards with explicit
  effective models, progress and failure reasons; avoid the wide empty column.
- AC7: overview uses clear goal/progress/verification/recent-event grouping;
  artifacts use responsive square cards with filename, file-type icon and full
  path on demand, retaining existing source/open actions.
- AC8: hovering a session shows available overview/recent information using the
  same white preview surface. Runtime-backed active task indicators appear on
  both session and parent expert without inventing completion/progress; honor
  prefers-reduced-motion. Loading/stale/empty data remains explicit.
- AC9 (user expansion): model error feedback is cross-cutting, including normal
  and streaming chat, Agent/background execution, auxiliary metadata generation,
  model testing and other existing model-driven features. Use a shared safe
  category contract and human-readable localized renderer; never dump upstream
  JSON into chat. Show cause and actionable next step, optional collapsed code/
  request ID, retain completed partial output on stream failure, and ensure
  credentials/request text never leak through user-facing error details.

## Build and validation

1. Implement catalog cache, merge, refresh endpoints and visible status (AC1–2).
2. Add standalone preset and verify its supported contract (AC4).
3. Add error classification and batch reason counts (AC3).
4. Share preview/modal components using ScheduleBrowser (AC5).
5. Targeted regression tests plus real controlled-provider/API/UI checks. Run
   repository checks before shipping; record public source and deployment SHA.

## Evidence and sources

2026-10-22 production: 48 failed jobs METADATA_GENERATION_FAILED, 2 ready.
Fictional tests: beam-free 403 RegionError; longcat-2.5-preview-free 402 endpoint
unavailable; minimax-m3.1-flash-free 410 ModelDeprecated. Models.dev marks the
latter two deprecated; official Go discovery only listed beam-free among free IDs.

- https://github.com/anomalyco/models.dev ; https://models.dev/api.json
- https://docs.opencode.ai/docs/go/ ; https://opencode.ai/zen/go/v1/models
- https://github.com/Ebony-Vinyl/dsh-our-free-model
- https://github.com/Ebony-Vinyl/dsh-our-free-model/blob/main/packages/standalone/README.md
