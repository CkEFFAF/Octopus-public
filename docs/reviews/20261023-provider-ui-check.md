# Provider catalog and conversation UI check

Baseline: `efe07b13b562cc86ed75c43669898324f8111d1a`.
Scope: `docs/specs/provider-catalog-task-popups.md`, AC1–AC9.

Read-only review covered account ownership, credential boundaries, cached catalog
failure behavior, saved settings precedence, Go protocol routing, safe error
rendering and partial-stream preservation, modal event propagation and artifact
opening. No unresolved release-blocking finding remains. Review was performed
by the implementing agent; no independent reviewer was available in this run.

- AC1–2: live Models.dev and official Go refresh succeeded from the deployment
  host using an independent cache. TTL/manual refresh/last-good failure behavior
  and protocol boundaries pass regression tests. Saved model choices retain
  explicit false/zero overrides through the existing effective-catalog merger.
- AC3/9: shared structured/text error categories cover chat, Agent retries,
  metadata, provider probes, voice, media and memory. Synthetic JSON/key-like
  errors render localized guidance; partial streaming text is retained. Metadata
  failures store safe codes and batches group counts by reason. Media HTTP tests
  prove locale propagation. No real chat content was sent in provider smokes.
  Final audit review also removed raw exception bodies from chat audit records
  and stream-error logs; a regression proves key/prompt text stays out of both
  persisted diagnostics and captured logs (gateway group5 passed).
- AC4: upstream `482500f7` source and verified Node 22.23.4 pilot passed fictional
  chat tests; `poolside/laguna-s-2.1:free` also passed Octop's actual GeneratedTitle
  and GeneratedBrief schema path. Deployment must supervise the loopback service
  and add its account-owned provider using the normal API.
- AC5/8: real local browser checks observed white expert/session task previews
  (computed RGB 255/255/255), scoped task dialogs and Escape closure with unchanged
  chat URL. Session hover includes overview, stage, recent events and update time.
  Runtime badges reuse existing activity observations and reduced-motion rules.
- AC6/7: desktop settings use two compact cards and 375px uses a single column.
  Artifact cards have type icons, short filenames and full-path accessible labels;
  desktop dimensions were 163.2px square. Mobile drawer content measures 375.2px
  and has no internal horizontal overflow; final 375px checks observed two
  138.4px square cards per row.
  Existing artifact/source interactions pass regression tests.

Verification: `make all PYTEST_JOBS=8` passed (5116 passed, 157 skipped), strict
mypy all 690 sources passed, full frontend Vitest 287 files / 1567 tests passed,
TypeScript passed. The final narrow-card CSS adjustment additionally passed the
overview/sidebar group (9 tests) and TypeScript. Logs are task-local under the
parent workspace tmp directory (`provider-ui-make-final-4.log`,
`provider-ui-final-vitest.log`, `provider-ui-layout-final.log`).

Browser limitation: ego-browser screenshot capture timed out; visual screenshots
were not obtained. Layout/computed-style/DOM and interaction checks were used.
Its emulated viewport and compositor animation do not stay synchronized across
rounds, so offscreen transition coordinates are not treated as layout evidence.
The same task space was retained throughout; no workaround browser was launched.

OpenCode Go fictional probes: Beam 403 region restriction, LongCat 402 endpoint
unavailable, MiniMax 410 retired. The release does not silently choose paid
alternatives. These provider availability limits are external to Octop.
