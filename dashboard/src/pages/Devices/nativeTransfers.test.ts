import { File as NodeFile } from "node:buffer";
import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { bytesToBase64 } from "./helpers";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("../../api/modules/execution", () => ({ executionApi: { call } }));
import {
  copyNativeFile,
  downloadNativeFile,
  uploadNativeFile,
} from "./nativeTransfers";

const CHUNK = 1024 * 1024;
const data = new Uint8Array(CHUNK + 17).fill(91);
const hash = (bytes: Uint8Array) =>
  createHash("sha256").update(bytes).digest("hex");
let corrupt = false;
let received: Uint8Array[];
beforeEach(() => {
  received = [];
  corrupt = false;
  call.mockReset();
  call.mockImplementation(
    async (
      context: string,
      action: string,
      params: Record<string, unknown>,
      signal?: AbortSignal,
    ) => {
      signal?.throwIfAborted();
      if (action === "fs.download.begin")
        return { transfer_id: "read", size: data.length, sha256: hash(data) };
      if (action === "fs.download.chunk") {
        const offset = Number(params.offset);
        const bytes = data.slice(offset, offset + CHUNK);
        if (corrupt) bytes[0] ^= 1;
        return {
          data_b64: bytesToBase64(bytes),
          size: data.length,
          offset,
          eof: offset + bytes.length === data.length,
        };
      }
      if (action === "fs.upload.begin")
        return { transfer_id: `${context}:write` };
      if (action === "fs.upload.chunk") {
        expect(params.transfer_id).toBe(`${context}:write`);
        received.push(
          new Uint8Array(Buffer.from(String(params.data_b64), "base64")),
        );
        return { bytes_done: Number(params.offset) + received.at(-1)!.length };
      }
      if (action === "fs.upload.commit")
        return { size: data.length, sha256: hash(data), path: "/target" };
      return { closed: true };
    },
  );
});

describe("native file transfers", () => {
  it("uploads one bounded chunk at a time with a full-file checksum", async () => {
    const file = new NodeFile([data], "sample.bin") as unknown as File;
    await uploadNativeFile(
      "frozen-gpu",
      "/workspace/sample.bin",
      file,
      new AbortController().signal,
      vi.fn(),
    );
    expect(received.map((bytes) => bytes.length)).toEqual([CHUNK, 17]);
    expect(call.mock.calls.every(([context]) => context === "frozen-gpu")).toBe(
      true,
    );
    expect(call).toHaveBeenCalledWith(
      "frozen-gpu",
      "fs.upload.begin",
      expect.objectContaining({
        path: "/workspace/sample.bin",
        sha256: hash(data),
        size: data.length,
      }),
      expect.any(AbortSignal),
    );
  });

  it("copies between two frozen contexts and commits only verified bytes", async () => {
    await copyNativeFile(
      "frozen-source",
      "/experiments/output.bin",
      "frozen-target",
      "D:/results/output.bin",
      new AbortController().signal,
      vi.fn(),
    );
    expect(received.map((bytes) => bytes.length)).toEqual([CHUNK, 17]);
    expect(call).toHaveBeenCalledWith(
      "frozen-target",
      "fs.upload.begin",
      expect.objectContaining({
        path: "D:/results/output.bin",
        sha256: hash(data),
        size: data.length,
      }),
      expect.any(AbortSignal),
    );
    expect(call).toHaveBeenCalledWith(
      "frozen-source",
      "fs.download.close",
      { transfer_id: "read" },
      undefined,
    );
  });

  it("aborts the destination and closes the source when the checksum changes", async () => {
    corrupt = true;
    await expect(
      copyNativeFile(
        "source",
        "/file",
        "target",
        "/new-file",
        new AbortController().signal,
        vi.fn(),
      ),
    ).rejects.toThrow("devices.checksumMismatch");
    expect(
      call.mock.calls.some(([, action]) => action === "fs.upload.commit"),
    ).toBe(false);
    expect(call).toHaveBeenCalledWith(
      "target",
      "fs.upload.abort",
      { transfer_id: "target:write" },
      undefined,
    );
    expect(call).toHaveBeenCalledWith(
      "source",
      "fs.download.close",
      { transfer_id: "read" },
      undefined,
    );
  });

  it("streams to a file writer and closes only after full verification", async () => {
    const writer = {
      write: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      abort: vi.fn(),
    };
    expect(
      await downloadNativeFile(
        "source",
        "/file",
        new AbortController().signal,
        vi.fn(),
        writer,
      ),
    ).toBeNull();
    expect(writer.write.mock.calls.map(([bytes]) => bytes.length)).toEqual([
      CHUNK,
      17,
    ]);
    expect(writer.close).toHaveBeenCalledOnce();
    expect(writer.abort).not.toHaveBeenCalled();
  });

  it("bounds the memory fallback before requesting file bytes", async () => {
    call.mockImplementation(async (_context: string, action: string) => {
      if (action === "fs.download.begin")
        return {
          transfer_id: "large",
          size: 257 * CHUNK,
          sha256: "0".repeat(64),
        };
      return { closed: true };
    });
    await expect(
      downloadNativeFile(
        "source",
        "/huge",
        new AbortController().signal,
        vi.fn(),
      ),
    ).rejects.toThrow("devices.native.browserDownloadLimit");
    expect(call.mock.calls.map(([, action]) => action)).toEqual([
      "fs.download.begin",
      "fs.download.close",
    ]);
  });
});
