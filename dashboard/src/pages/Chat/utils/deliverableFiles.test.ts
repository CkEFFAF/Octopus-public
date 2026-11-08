import { expect, it } from "vitest";
import { deliverableKind } from "./deliverableFiles";

it.each([
  ["plot.csv", "image/png", "image"],
  ["FIGURE.PNG", "application/octet-stream", "image"],
  ["report.PDF", "application/octet-stream", "document"],
  ["results.csv", "text/csv", "data"],
  [
    "table",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "data",
  ],
  ["analysis.ipynb", "application/json", "code"],
  ["source.py", "text/plain", "code"],
  ["output.tar.gz", "application/octet-stream", "archive"],
  ["recording", "audio/mpeg", "media"],
  ["weights.bin", "application/octet-stream", "other"],
])(
  "classifies %s using MIME and a filename fallback",
  (name, media_type, kind) => {
    expect(deliverableKind({ name, media_type })).toBe(kind);
  },
);
