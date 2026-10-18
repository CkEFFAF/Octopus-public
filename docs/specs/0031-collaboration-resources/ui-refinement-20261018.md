# Collaboration and resource UI refinement

Date: 2026-10-18 (Asia/Shanghai)
Baseline: 323f585efd3a9aafe279e936f14f5114275fbf7d
Branch: hotfix/resource-delivery-cards
Contract: bounded correction to [0031](index.md), revision 2026-10-18.4.
Status: implemented, independently source-reviewed and locally verified; Git publication and controlled rollout in progress.

## Authority and isolation

The user requested compact file cards with type icons, accurate delivery status, and unobstructed download actions. The user added the expert collaboration UI and then explicitly chose an entry in the right toolbar that opens a popup. This last instruction replaces the permanent inline collaboration panel design.

Implementation is isolated in `octopus-resource-delivery-ui`. Preserve the existing `feat/agent-live-message-steering` working tree and all its unrelated changes. Root owns architecture and this record; GPT-6.1 Sol medium implements, GPT-6 Luna high independently reviews, and GPT-5.6 Luna high handles Git publication and authorized endpoint updates.

## Decisions and acceptance

| ID | Required behavior | Verification |
| --- | --- | --- |
| UI1 | Published resources use compact responsive cards with an appropriate file type icon, readable name, concise metadata and preview/download actions. Long names and hashes do not stretch the container. | Component behavior checks and actual desktop/narrow viewport inspection when tooling permits. |
| UI2 | Real delivery success requires target acknowledgement, matching byte count and checksum, and a persisted completed projection. A successful retry clears only stale delivery failure reasons. Publication alone never implies delivery. | Domain regression: failed then successful retry; start/terminal compare-and-set conflicts; bad acknowledgement/checksum still fails. |
| UI3 | Resource actions remain reachable without overlap from the right toolbar, including narrow screens. Existing owner authorization and snapshot content access remain intact. | Layout/interaction verification, preview and download regressions. |
| UI4 | The existing right toolbar has an accessible expert collaboration button. Clicking opens a closable popup containing collaboration summary, refresh, members and resources. The conversation no longer permanently mounts the large collaboration panel. Member identity, actual device, transport status and task result remain distinct and legible. | Entry/open/close, refresh, detail/preview interactions, keyboard behavior and responsive layout checks. |

Reuse the current React components, Ant Design dialog, icon system, API contract and locale mechanism. A completed transport with an unknown task result remains unknown. Opening the popup must not dispatch work. UI loading, failure and unavailable resource states remain explicit.

For delivery persistence, check the existing repository compare-and-set return values. A failed start cannot perform device writes; concurrent running attempts cannot silently duplicate delivery. A failed terminal persistence cannot return a completed receipt or overwrite newer state, and must distinguish state synchronization conflict from a failed device transfer. Do not automatically repeat side effects. Preserve all existing destination, work-mode, ownership, acknowledgement and checksum checks. No schema migration or new execution backend is needed.

## Verification record

The frozen tracked diff SHA256 is `c94edddb461b8cfcc78d530cf8027897584edb08567845e59664cfc9ceb49db1` (`git diff --binary HEAD`, excluding this then-untracked record). Current checks pass: frontend components 14, resource domain 19, resource API 3, TypeScript, affected Ruff/Prettier checks, CRLF-aware diff check, and Vite production build. Build output and temporary fixtures were isolated and removed from the source diff.

Real Edge browser checks loaded the changed React component and styles with synthetic fixture data at desktop width 1280 and mobile width 375. Root inspected desktop, mobile and mobile-scrolled screenshots. Both viewports have no horizontal overflow; opening/closing, Enter to open and Escape to close pass. Every download action remains reachable after scrolling and its center hit-test resolves to the button itself. Mobile content scrolls to the last resource while dialog controls remain accessible. Evidence is in workspace `ops/resource-delivery-ui/` (`desktop.png`, `mobile.png`, `mobile-scrolled.png`, `browser-acceptance.log`, `component-results.json`). This fixture does not use production data and is not evidence of a live GPU/laptop transfer or deployed endpoint update.

Independent review and the current full repository gate remain pending. Historical results in [verification.md](verification.md) are context only and do not establish that this new diff passes.

## Final local acceptance

The corrected combined source passed actual `make all PYTEST_JOBS=4` with exit0:4939 passed,157 skipped,20 warnings in729.36seconds. Ruff/format and mypy passed before pytest. Full stdout/stderr and exit marker are retained in workspace `ops/resource-delivery-ui/final-make-all.log`. The earlier3-failure run remains separately recorded; it was not relabeled as green.

Independent GPT-6 Luna high review recomputed the24-file result/dependency fingerprint `a66e60dd513921c8db0d6bd685cd077fe2d93970e0720d62af38f9d5638d380f` and the two-test correction fingerprint `efeab00dab6080c46cc894a280ff702047fe34443a83bf9eb2a0112e3d1f4073`, with no remaining substantive finding. Sharing layout and snapshot behavior also passed read-only source review.

A fresh real-component Edge fixture verified independent call/result labels for succeeded, failed, historical unknown with/without reply and running at1280/375. Source provenance/summary is visible; unknown remains neutral. Hidden reasoning/system test sentinels are absent. Scroll, verified synthetic download, preview and Escape work. Root inspected desktop/mobile screenshots in `ops/resource-delivery-ui/results-ui-*.png`. These are synthetic local UI checks; live production acceptance is a separate controlled rollout step, currently in progress.
