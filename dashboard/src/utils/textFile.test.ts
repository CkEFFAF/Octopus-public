import { describe, expect, it } from "vitest";
import { decodeUtf8Text, isTextFile, isMarkdownFile } from "./textFile";
describe("portable text previews", () => {
  it.each([
    ["report.MD", "application/octet-stream"],
    ["report.markdown", "text/plain"],
    ["report", "text/markdown; charset=utf-8"],
    ["report", "application/markdown"],
  ])("recognizes rendered Markdown %s (%s)", (name, mime) => {
    expect(isMarkdownFile(name, mime)).toBe(true);
    expect(isTextFile(name, mime)).toBe(true);
  });
  it.each([
    "script.js",
    "script.sh",
    "settings.yaml",
    "config.yml",
    "settings.toml",
    "script.ps1",
    "run.log",
    "C:\\project\\Dockerfile",
    ".env.local",
  ])("recognizes %s regardless of host MIME", (name) => {
    expect(isTextFile(name, "application/octet-stream")).toBe(true);
    expect(
      decodeUtf8Text(new TextEncoder().encode("# text\nhello 中文")),
    ).toContain("中文");
  });
  it("does not classify arbitrary binaries as text", () => {
    expect(isTextFile("archive.bin")).toBe(false);
    expect(() => decodeUtf8Text(new Uint8Array([0xff]))).toThrow();
    expect(() => decodeUtf8Text(new Uint8Array([65, 0, 66]))).toThrow();
  });
});
