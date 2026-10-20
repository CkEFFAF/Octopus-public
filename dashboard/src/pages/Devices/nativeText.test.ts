import { describe, expect, it } from "vitest";
import { decodeEditableText, encodeEditableText } from "./nativeText";

describe("native UTF-8 byte conventions", () => {
  for (const eol of ["\n", "\r\n"])
    for (const bom of [true, false]) {
      it(`preserves BOM=${bom} and ${JSON.stringify(
        eol,
      )} after editing`, () => {
        const input = new TextEncoder().encode(
          (bom ? "\ufeff" : "") + ["# 中文", "print(1)", ""].join(eol),
        );
        const decoded = decodeEditableText(input);
        const saved = encodeEditableText(
          decoded.text.replace("print(1)", "print(2)"),
          decoded.bom,
          decoded.eol,
        );
        expect(Array.from(saved)).toEqual(
          Array.from(
            new TextEncoder().encode(
              (bom ? "\ufeff" : "") + ["# 中文", "print(2)", ""].join(eol),
            ),
          ),
        );
      });
    }
  it("rejects binary and invalid UTF-8", () => {
    expect(() => decodeEditableText(new Uint8Array([0]))).toThrow();
    expect(() => decodeEditableText(new Uint8Array([0xff]))).toThrow();
  });
});
