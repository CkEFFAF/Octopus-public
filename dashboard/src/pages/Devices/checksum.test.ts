import { describe, it, expect } from "vitest";
import { sha256Portable } from "./helpers";

describe("LAN mobile checksum without secure-context WebCrypto", () => {
  it.each([
    ["", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    ["abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
    [
      "a".repeat(1000000),
      "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
    ],
  ])("matches known SHA-256 vectors (%s)", (input, expected) => {
    expect(sha256Portable(new TextEncoder().encode(input))).toBe(expected);
  });
});
