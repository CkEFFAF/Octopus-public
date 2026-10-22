/**
 * 0036 S0 — ProviderCard「更新模型」前后截图。
 *
 * Prefer the standalone capture helper (no package.json change):
 *   node docs/specs/assets/0036/capture-screens.mjs
 *
 * Or with @playwright/test available:
 *   npx playwright test dashboard/e2e/provider-models-refresh.spec.ts
 */
import { test, expect } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "../..");
const fixture = path.join(root, "docs/specs/assets/0036/card-fixture.html");
const outDir = path.join(root, "docs/specs/assets/0036");

test.describe("0036 provider models refresh card", () => {
  test("captures before and after screenshots", async ({ page }) => {
    await page.goto(`file://${fixture}?state=before`);
    await expect(page.getByTestId("provider-refresh-models")).toBeVisible();
    await page.locator('[data-testid="provider-card"]').screenshot({
      path: path.join(outDir, "before-card.png"),
    });

    await page.goto(`file://${fixture}?state=after`);
    await expect(page.getByTestId("refresh-toast")).toBeVisible();
    await page.locator("body").screenshot({
      path: path.join(outDir, "after-card.png"),
    });
  });
});
