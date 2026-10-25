import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("PublicMarkdown isolation (AC10 / AC-M16)", () => {
  it("does not import Mermaid or the shared chat Markdown loader", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(here, "PublicMarkdown.tsx"), "utf8");
    expect(src).not.toMatch(/mermaid/i);
    expect(src).not.toMatch(/loadMermaid|sanitizeMermaidSvg|mermaidLoader/);
    expect(src).toMatch(/skipHtml/);
  });
});
