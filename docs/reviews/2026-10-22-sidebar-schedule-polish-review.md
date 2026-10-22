# Review, hotfix/sidebar-schedule-popover, 2026-10-22

**Reviewed by**: Independent Codex review agent (runtime model identifier not exposed; author: Codex)
**Scope**: 15 files, combined uncommitted changes against `3010719ed38db701ee2221ee86c7a0924e9e5d08`; includes the final CHANGELOG line and excludes temporary sidebar QA fixture files and this review report.
**Verdict**: Approve

## Summary

The change bounds the clock hover preview to two upcoming or recently fired tasks, adds actual fire-time metadata, routes clock activation to the matching conversation's schedules/reminders workbench, and adds the matching Share2 icon to the title-bar share menu. The data additions retain existing authorization and omit prompts; route scope checks and keyboard propagation guards are appropriate. The production-theme integration issue found in the first pass is resolved; no outstanding actionable findings remain.

## Resolved during review

### Match the application's tooltip prefix

The initial inner-tooltip overrides targeted `.ant-tooltip-inner`, but the application uses `prefixCls="octop"`. On the explicitly elevated background, task titles could consequently inherit Ant Design's light foreground in the light theme. The final code removes the prefix-dependent selector and supplies padding, border, primary text color and shadow through `Tooltip.overlayInnerStyle`.

Rereview inspected that supported component styling and the updated regression rendered under the production prefix, asserting the actual tooltip's `.octop-tooltip-inner` class and primary text color. Author-reported browser DOM checks under the same prefix confirm dark text on white in the light theme and light text on dark in the dark theme, preserving two items and approximately 186.9px height. The issue is resolved.

## Strengths

- Preview size is explicitly bounded to two rows; upcoming tasks sort by nearest next run, historical rows use their actual last-run timestamp, and titles have a two-line clamp.
- Clock click and Enter/Space stop row selection and navigate through encoded agent/thread segments. The agent ID is derived from the account-scoped observation map; no cross-scope mutation controls are introduced.
- Workbench deep links validate the current route's agent and thread, open the requested schedules/reminders page, close on scope mismatch, and remove only the consumed query parameter on close.
- Backend response fields are minimal and continue through the existing owner/thread filters; the share-menu regression checks the same Share2 icon used by the sidebar.

## Test coverage

Inspected the added nearest-two/latest-past preview and click/keyboard navigation cases, schedules/reminders deep-link and close-query tests, scope mismatch test, share-icon assertion, and backend metadata checks. Final supplied evidence reports **51 frontend tests passed across six files**, including the production-prefix styling regression, and **77 backend/i18n tests passed**. TypeScript passed; targeted ESLint reported zero errors and one existing epoch-ref warning. No application-source changes followed the 51-test rerun. Final full hook/build/CI gates remain delivery checks; no full-suite result is inferred from earlier work.

The author reported real browser DOM hover inspections with eight historical tasks under the production prefix: exactly two preview items, about 186.9px high, including a 200px sidebar in dark mode. Light foreground/background values were `rgb(17, 24, 39)` / `rgb(255, 255, 255)`; dark values were `rgba(255, 255, 255, 0.9)` / `rgb(30, 30, 30)`. Both classic and minimal layouts showed two items on actual hover, and clock activation in each opened one task-workbench dialog on the self-reminders page with eight items. The actual title-bar menu exposed the Share2 icon. Screenshot capture timed out, so this report claims no screenshot evidence. Final regression evidence is recorded in `sidebar-polish-regression-20261022.log` (local evidence kept outside the repository). Final hook/build/CI gates remain delivery checks, and this source approval does not claim they have finished.
