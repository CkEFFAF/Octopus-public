# Provider catalog, model errors and conversation UI

Implementation verified on 2026-10-23. Merge/deployment pending.
User instruction: complete every improvement before merging and deploying to
https://octop.effaf.me. No partial release. Skip Windows CI if needed; normal
local hooks remain required. No current-phase deployment yet.

Worktree: D:/Agent_Workspace/octopus/conversation-batch-all
Branch: fix/live-provider-catalog-and-task-popups
Baseline and currently deployed source: efe07b13b562cc86ed75c43669898324f8111d1a
Latest origin/main fetch matches that baseline. The unrelated original schedule
worktree is untouched.

## Implemented

- Models.dev + official OpenCode Go live public catalogs, first scheduled check
  within a minute of startup, 24h TTL, 1h failure retry and manual refresh.
  Last-good disk snapshots survive restart and upstream failures. Status shows
  source, last success and stale/failure state. No account keys sent upstream.
- Discovery no longer filters new Go models through obsolete bundled IDs.
  Protocol separation and explicit saved settings are retained. New OpenAI Go
  models receive Responses API metadata where required by upstream.
- Our Free Model editable loopback preset and live model discovery. Upstream
  standalone source pinned/audited at 482500f79ecbf92f581e1d2e98f170701a743083.
- Shared safe errors across chat/streams, Agent retries, metadata, probes, voice,
  media, memory and background work. Region/retirement/access/auth/quota/network
  reasons are localized. Retry prompts contain stable categories, never bodies.
  Metadata batches group failed counts by reason; partial stream text survives.
- Compact responsive organization settings, overview sections, typed square
  artifact cards with short filename/full path, preserved source/open actions.
- White expert/session previews, scoped task dialogs that preserve chat URL and
  selection, session hover stage/recent events/update time, runtime-backed
  expert/session working indicators with reduced-motion support.

## Verification

- make all PYTEST_JOBS=8: 5116 passed,157 skipped; Ruff and strict mypy690 green.
  Log: parent tmp/provider-ui-make-final-4.log.
- Full frontend: 287 files/1567 tests passed, maxWorkers2. TypeScript green.
  Log: parent tmp/provider-ui-final-vitest.log.
- Final narrow-card CSS: overview/sidebar9 tests + TypeScript passed.
  Log: parent tmp/provider-ui-layout-final.log.
- Final component-prefix CSS correction: settings/overview6 tests passed;
  log parent tmp/provider-ui-css-final.log. Normal hook builds the final CSS.
- Media locale and protocol isolation integration group:7 passed.
- Final audit review replaced raw chat exception audit/log entries with safe
  category/type/status diagnostics; gateway group5 passed. A final full check
  for this last backend correction passed in provider-ui-make-final-4.log.
  Merging must still wait for the normal commit hook and CI.
- Review: docs/reviews/20261023-provider-ui-check.md covers AC1-AC9.
- Browser space14/p1 was reused. White tooltip computedRGB255/255/255;
  session and expert dialogs close with Escape and preserve URL; session scope
  and recent overview events observed. Desktop artifacts163.2px square;
  mobile drawer375.2px with no internal overflow. Screenshot capture failed;
  compositor/emulation transitions are unreliable, so DOM/style/interactions
  provide the recorded evidence. Never claim screenshots were viewed.

## Provider smoke and operational preparation

All provider smokes used fictional text and did not print credentials.
OpenCode Go: Beam403 RegionError; LongCat402 endpoint unavailable; MiniMax410
retired. No free Go model was usable from this server at test time.

Our Free Model pilot is /root/our-free-model-pilot on octop-cloud. Official
SHA256-verified Node22.23.4 is isolated there; system Node is unchanged.
Standalone listens127.0.0.1:18900 with --no-lan. Private data/settings.json holds
its forwarding key; pilot.log contains a one-time login link, never print them.
Source archive SHA256:
0828845a36d60e1544960bf7cf6df0a7d62e75715ddd2ba1af6c21de4a483171.
Fictional chat passed kilo-auto/free, nvidia/nemotron-3.5-lightning:free and
poolside/laguna-s-2.1:free. The latter passed actual Octop GeneratedTitle and
GeneratedBrief schemas; Nemotron timed out on that stricter30s path.
Live catalog refresh from the cloud succeeded for both official public sources.

Standalone operational preparation is complete: systemd service
octop-our-free-model.service is healthy and enabled, bound only127.0.0.1:18900.
Its key/data backup is /root/our-free-model-pilot/backups/1792690440. Fictional
GeneratedTitle and GeneratedBrief schema tests both passed again after promotion.
The original pilot process has been replaced by the supervised service.

Next operational steps:
1. Finish normal commit hook, push and create/attach PR. Check Linux CI/latest
   main/conflicts, merge exact verified head.
2. Build committed dashboard bundle, prepare/rehearse release and private backup.
3. Preserve the supervised service and private key/data during the hub release.
4. Activate backed-up Octop release and verify public asset/source equality.
5. Account API add Our Free Model, enable tested free models and set metadata to
   poolside/laguna-s-2.1:free without changing default chat model or paid fallback.
   Script parent tmp/provider-ui-configure-ofm.py keeps keys/JWT in memory.
6. Recheck health/resources/auth/public feature assets. Record PR and deployed SHA.

Current production: octop-hub.service, port8188, /root/OctopData, schema33,
source /root/octopus-deployments/conversation-metadata-20261022-efe07b13.
Earlier backup: /root/octopus-deployments/backups/conversation-metadata-efe07b13-1792682073.
New release scripts must use a new dated target, preserve service environment and
user data, and retain rollback. Local QA services ports18136/18137 and Vite5175
belong to this task; stop only these at completion. Browser space14 must be
finished once at the end; never recreate it to recover a failure.
