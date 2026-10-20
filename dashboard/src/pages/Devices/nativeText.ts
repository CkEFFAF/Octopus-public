import { decodeUtf8Text } from "../../utils/textFile";

/** Keep UTF-8 byte conventions when Monaco normalizes line endings. */
export function decodeEditableText(bytes: Uint8Array) {
  const bom = bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf;
  const text = decodeUtf8Text(bytes);
  const eol = text.includes("\r\n") ? "\r\n" : "\n";
  return { text, bom, eol };
}
export function encodeEditableText(
  text: string,
  bom: boolean,
  eol: string,
  original?: string,
) {
  const lines = text.split(/\r\n|\n|\r/);
  const originalParts = original?.split(/(\r\n|\n|\r)/) ?? [];
  const oldLines = originalParts.filter((_, i) => i % 2 === 0);
  let prefix = 0;
  while (prefix < lines.length && lines[prefix] === oldLines[prefix]) prefix++;
  let suffix = 0;
  while (
    suffix < lines.length - prefix &&
    suffix < oldLines.length - prefix &&
    lines[lines.length - 1 - suffix] === oldLines[oldLines.length - 1 - suffix]
  )
    suffix++;
  const value = lines
    .map((line, i) => {
      if (i === lines.length - 1) return line;
      const oldIndex =
        i < prefix
          ? i
          : i >= lines.length - suffix
          ? oldLines.length - (lines.length - i)
          : i;
      return line + (originalParts[oldIndex * 2 + 1] ?? eol);
    })
    .join("");
  return new TextEncoder().encode((bom ? "\ufeff" : "") + value);
}
