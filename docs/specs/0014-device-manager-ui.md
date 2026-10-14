# Device management UI

Status: Implemented and verified.

Base: `f9f6017a4759261816b4106215b7587b9f661660` (v1.0.2b9). User requested a clearer device page, Git/release publication and updating both cloud services.

## Contract

- Use compact full-width device rows, clear name/status hierarchy, platform/shared-folder summary and last seen. Long names cannot displace status or actions.
- Primary action opens the first supported workspace in files → desktop → command order. Direct tool buttons remain; all permission checks, desktop takeover confirmation and unavailable/offline/revoked behavior stay intact.
- Search by device name/platform/ID and filter by all/online/offline (revoked belongs only to all). Empty results offer clearing filters. Loading and failure remain visible.
- Secondary management actions use quiet buttons. Management-host tools and existing HTTP connection explanation remain accessible in expandable sections with a visible connection label.
- Preserve rename, details, authorization, records, access keys and pairing flows. Chinese/English labels, keyboard controls, desktop/mobile layouts and dark-mode theme tokens.
- Verify behavior with existing device tests plus filter/workspace regressions and real desktop/mobile UI. Publish v1.0.2b10 through hotfix → main, then upgrade cloud management and execution services with private backups and preserved data/registration.

## Evidence (2026-10-14)

- Device Vitest suite: 26 tests passed (4 files), including filtering, revoked primary action, exact target selection, rename, details, unavailable capabilities and desktop controls.
- Targeted ESLint passed without errors or warnings; production `npm run build` passed, including TypeScript. Lock check and 8 release/portable tests passed.
- Browser verified a real connected client in isolated localhost acceptance data, an offline device, search/clear behavior, status filtering, expandable host tools/HTTP explanation, and the selected device's actual README file through its workspace.
- Desktop and 390px mobile UI inspected; mobile main width and scroll width both 390px, with no horizontal overflow. Test registrations were confined to the local acceptance environment.
- Actual application uses the `octop-` component prefix. Device CSS now explicitly matches both test/default `ant-` and runtime `octop-` selectors, so toolbar sizing, search width, selected filters, drawer wrapping and mobile targets apply in production.
- Independent source review approved: `docs/reviews/20261014-devices-ui-check.md`. Backend APIs, database schema, ownership and device registration behavior are unchanged.
