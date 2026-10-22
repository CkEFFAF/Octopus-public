import { chromium } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const root = "/workspace/Octopus-public";
const fixture = path.join(root, "docs/specs/assets/0036/card-fixture.html");
const outDir = path.join(root, "docs/specs/assets/0036");
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 480, height: 420 } });

await page.goto(`file://${fixture}?state=before`);
await page.locator('[data-testid="provider-card"]').screenshot({
  path: path.join(outDir, "before-card.png"),
});

await page.goto(`file://${fixture}?state=after`);
await page.locator("body").screenshot({
  path: path.join(outDir, "after-card.png"),
});

await browser.close();
console.log("wrote before-card.png and after-card.png");
