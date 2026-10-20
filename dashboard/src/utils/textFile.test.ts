import { describe, expect, it } from "vitest";
import { decodeUtf8Text, isTextFile } from "./textFile";
describe("portable text previews", () => {
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
