# 0036 assets

- `before-card.png` / `after-card.png` — Playwright Chromium screenshots of the ProviderCard「更新模型」control (fixture: `card-fixture.html`).
- Regenerate:

```bash
# from a directory with `playwright` installed
node docs/specs/assets/0036/capture-screens.mjs
# or
npx playwright test dashboard/e2e/provider-models-refresh.spec.ts
```
