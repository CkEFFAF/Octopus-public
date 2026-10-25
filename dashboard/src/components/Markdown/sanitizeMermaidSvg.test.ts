import { describe, expect, it } from "vitest";
import { sanitizeMermaidSvg } from "./sanitizeMermaidSvg";

describe("sanitizeMermaidSvg", () => {
  it("strips inline event handlers", () => {
    const raw =
      '<svg xmlns="http://www.w3.org/2000/svg"><g onclick="alert(1)" onload="evil()"><text>ok</text></g></svg>';
    const out = sanitizeMermaidSvg(raw);
    expect(out.toLowerCase()).not.toMatch(/\son[a-z]+\s*=/);
    expect(out).toContain("ok");
  });

  it("removes javascript: href and xlink:href", () => {
    const raw = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
      <a href="javascript:window.auditFlags=1"><text>click</text></a>
      <a xlink:href="javascript:void(0)"><text>x</text></a>
    </svg>`;
    const out = sanitizeMermaidSvg(raw);
    expect(out.toLowerCase()).not.toContain("javascript:");
  });

  it("keeps safe http(s) links", () => {
    const raw =
      '<svg xmlns="http://www.w3.org/2000/svg"><a href="https://example.com/docs"><text>docs</text></a></svg>';
    const out = sanitizeMermaidSvg(raw);
    expect(out).toContain("https://example.com/docs");
  });

  it("removes nested script elements", () => {
    const raw =
      '<svg xmlns="http://www.w3.org/2000/svg"><script>window.x=1</script><text>t</text></svg>';
    const out = sanitizeMermaidSvg(raw);
    expect(out.toLowerCase()).not.toContain("<script");
    expect(out).toContain("t");
  });

  it("returns empty for non-svg garbage", () => {
    expect(sanitizeMermaidSvg("<div>not svg</div>")).toBe("");
  });

  it("is a no-op for blank input", () => {
    expect(sanitizeMermaidSvg("")).toBe("");
    expect(sanitizeMermaidSvg("   ")).toBe("   ");
  });
});
