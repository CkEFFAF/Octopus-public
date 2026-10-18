# Sharing UI refinement

Date: 2026-10-18 (Asia/Shanghai)
Revision: 2026-10-18.1
Status: implemented, independently source-reviewed and locally verified; Git publication and controlled rollout in progress.
Parent contract: [0032](index.md). The existing snapshot/owner/token/privacy contract is unchanged.

## Requirements and design

| ID | Observable acceptance |
| --- | --- |
| SU1 | Both session menus show a leading outline share icon matching neighboring item size, stroke and spacing. Preserve share behavior and ownership. |
| SU2 | ShareManagementDialog has a compact title/description, an explicit privacy/review notice, and a session summary with title, message count and snapshot timezone. Use clear spacing and existing theme tokens, with no redundant large headings. |
| SU3 | The exact public snapshot remains fully reviewable in a bounded scrollable preview. Improve role/message/Markdown spacing; long content, tables and code cannot stretch the dialog or hide controls. Refresh preview, expiry selection and create action are clearly grouped and remain reachable at desktop and 375px. Preserve stale-digest refusal and disable create while preview is absent/loading. |
| SU4 | Existing links use compact cards/rows with readable titles, status tags (active/expired/revoked), creation/expiry metadata and existing copy/close actions. Preserve server-timezone display, paging, read-only URLs, no live URLs on revoked/expired entries, async loading/error feedback and scope isolation. |
| SU5 | Global share management follows the project's settings-page content alignment and responsive width. Remove duplicate page/list titles; use the shared list with a suitable heading option rather than fork its data or behavior. Avoid the current narrow floating text column and excessive vertical whitespace. Empty/loading/failure states are explicit. |
| SU6 | Keep all existing privacy facts visible and accurate: anonymous link access, fixed reviewed snapshot, later messages stay private, excluded attachments/tool activity/reasoning, ordinary text can contain secrets, and closing a link cannot retract saved copies. Preserve the existing public renderer; no additional data is shared. |

Reuse Ant Design and sharing.module.less. Candidate files: components/Sharing/ShareManagementDialog.tsx, ShareList.tsx, ShareMessages.tsx, sharing.module.less; pages/ThreadShares/index.tsx and a page-local stylesheet if warranted. The two Chat session menu files already have a minimal Share2 change for SU1. Do not edit Chat/index.tsx or CollaborationPanel while the collaboration coder owns those files. Coordinate shared dashboard zh/en locale additions with the single locale writer.

## Build and verification

Implement the menu icons and compact popup/list/page layouts (SU1-6), then run existing sharing/sidebar tests, frontend typecheck, affected lint/format and production build. Add behavior regressions only where layout changes affect a real interaction or existing state. Inspect real changed React components at desktop and 375px with synthetic active/expired/revoked and long preview content. Verify refresh, expiry/create visibility, copy/revoke/paging, dialog close and keyboard behavior without creating or revoking production shares.

Root owns this record, coder GPT-6.1 Sol medium implements, GPT-6 Luna high independently reviews and the designated Git/deployment role integrates the finished change. No unrelated source formatting or sharing backend/API redesign is authorized by this UI request.

## Local implementation verification, 2026-10-18

Sharing UI is frozen for integrated review. Current checks pass: Sharing21 tests (including accessible section and single heading), ChatTitleBar/Layout8 tests, TypeScript, affected ESLint/Prettier and diff checks, and isolated Vite production/PWA build. Existing stale409 snapshot checks remain covered; no new backend/API/locale behavior was introduced by this UI slice.

Real changed React components were inspected in Edge at1280 and375 pixels with synthetic data. Refresh, create, copy, revoke, pagination and Escape pass; dialog body and exact preview scroll, footer controls remain reachable, long code/table content does not create horizontal page overflow, and management uses one page title. Root inspected desktop/mobile dialog and management screenshots. Evidence: workspace `ops/resource-delivery-ui/sharing-{1280,1280-links,375,375-links,page-1280,page-375}.png`, scripts/metrics and `sharing-test-results.json`. No production conversation or share was created or revoked. Temporary fixture source, isolated build output and preview process were cleaned.

Independent integrated review and current repository gate/publication/rollout are not complete. These local UI checks are not evidence of a live endpoint update.

## Final local acceptance

The corrected combined source passed actual `make all PYTEST_JOBS=4` with exit0:4939 passed,157 skipped,20 warnings in729.36seconds. Ruff/format and mypy passed before pytest. Full stdout/stderr and exit marker are retained in workspace `ops/resource-delivery-ui/final-make-all.log`. The earlier3-failure run remains separately recorded; it was not relabeled as green.

Independent GPT-6 Luna high review recomputed the24-file result/dependency fingerprint `a66e60dd513921c8db0d6bd685cd077fe2d93970e0720d62af38f9d5638d380f` and the two-test correction fingerprint `efeab00dab6080c46cc894a280ff702047fe34443a83bf9eb2a0112e3d1f4073`, with no remaining substantive finding. Sharing layout and snapshot behavior also passed read-only source review.

A fresh real-component Edge fixture verified independent call/result labels for succeeded, failed, historical unknown with/without reply and running at1280/375. Source provenance/summary is visible; unknown remains neutral. Hidden reasoning/system test sentinels are absent. Scroll, verified synthetic download, preview and Escape work. Root inspected desktop/mobile screenshots in `ops/resource-delivery-ui/results-ui-*.png`. These are synthetic local UI checks; live production acceptance is a separate controlled rollout step, currently in progress.
