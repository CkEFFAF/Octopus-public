import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { executionApi } from "../../api/modules/execution";
import { base64ToBytes, bytesToBase64 } from "./helpers";

const CHUNK = 1024 * 1024;
export class NativeTransferError extends Error {
  readonly key: string;
  constructor(key: string) {
    super(key);
    this.key = key;
  }
}
type Progress = (done: number, total: number) => void;
interface Begin {
  transfer_id: string;
  size: number;
  sha256: string;
}
interface Receipt {
  size: number;
  sha256: string;
  path: string;
}
const call = <T>(
  context: string,
  action: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
) => executionApi.call<T>(context, action, params, signal);
async function close(context: string, kind: "upload" | "download", id: string) {
  try {
    await call(context, `fs.${kind}.${kind === "upload" ? "abort" : "close"}`, {
      transfer_id: id,
    });
  } catch {
    /* Device idle cleanup also closes an interrupted stream. */
  }
}

export async function uploadNativeFile(
  context: string,
  path: string,
  file: File,
  signal: AbortSignal,
  progress: Progress,
): Promise<Receipt> {
  const digest = sha256.create();
  for (let offset = 0; offset < file.size; offset += CHUNK) {
    signal.throwIfAborted();
    digest.update(
      new Uint8Array(await file.slice(offset, offset + CHUNK).arrayBuffer()),
    );
  }
  const hash = bytesToHex(digest.digest());
  signal.throwIfAborted();
  const session = await call<Begin>(
    context,
    "fs.upload.begin",
    { path, size: file.size, sha256: hash },
    signal,
  );
  let committed = false;
  try {
    for (let offset = 0; offset < file.size; offset += CHUNK) {
      const bytes = new Uint8Array(
        await file.slice(offset, offset + CHUNK).arrayBuffer(),
      );
      const ack = await call<{ bytes_done: number }>(
        context,
        "fs.upload.chunk",
        {
          transfer_id: session.transfer_id,
          offset,
          data_b64: bytesToBase64(bytes),
        },
        signal,
      );
      if (ack.bytes_done !== offset + bytes.length)
        throw new NativeTransferError("devices.chunkMismatch");
      progress(ack.bytes_done, file.size);
    }
    const result = await call<Receipt>(
      context,
      "fs.upload.commit",
      { transfer_id: session.transfer_id },
      signal,
    );
    if (result.sha256 !== hash || result.size !== file.size)
      throw new NativeTransferError("devices.checksumMismatch");
    committed = true;
    return result;
  } finally {
    if (!committed) await close(context, "upload", session.transfer_id);
  }
}

async function readNativeFile(
  context: string,
  path: string,
  signal: AbortSignal,
  progress: Progress,
  consume: (bytes: Uint8Array, session: Begin, offset: number) => Promise<void>,
  begin?: (session: Begin) => Promise<void>,
) {
  const session = await call<Begin>(
    context,
    "fs.download.begin",
    { path },
    signal,
  );
  try {
    await begin?.(session);
    const digest = sha256.create();
    let offset = 0;
    while (offset < session.size) {
      const part = await call<{
        data_b64: string;
        offset: number;
        eof: boolean;
        size: number;
      }>(
        context,
        "fs.download.chunk",
        { transfer_id: session.transfer_id, offset },
        signal,
      );
      const bytes = base64ToBytes(part.data_b64);
      if (
        part.offset !== offset ||
        part.size !== session.size ||
        !bytes.length ||
        bytes.length > CHUNK ||
        offset + bytes.length > session.size ||
        part.eof !== (offset + bytes.length === session.size)
      )
        throw new NativeTransferError("devices.native.changedDuringRead");
      digest.update(bytes);
      await consume(bytes, session, offset);
      offset += bytes.length;
      progress(offset, session.size);
    }
    if (bytesToHex(digest.digest()) !== session.sha256)
      throw new NativeTransferError("devices.checksumMismatch");
    return session;
  } finally {
    await close(context, "download", session.transfer_id);
  }
}

export async function copyNativeFile(
  source: string,
  sourcePath: string,
  target: string,
  targetPath: string,
  signal: AbortSignal,
  progress: Progress,
): Promise<Receipt> {
  let upload = "";
  let committed = false;
  try {
    const info = await readNativeFile(
      source,
      sourcePath,
      signal,
      progress,
      async (bytes, _session, offset) => {
        const ack = await call<{ bytes_done: number }>(
          target,
          "fs.upload.chunk",
          {
            transfer_id: upload,
            offset,
            data_b64: bytesToBase64(bytes),
          },
          signal,
        );
        if (ack.bytes_done !== offset + bytes.length)
          throw new NativeTransferError("devices.chunkMismatch");
      },
      async (info) => {
        const started = await call<Begin>(
          target,
          "fs.upload.begin",
          {
            path: targetPath,
            size: info.size,
            sha256: info.sha256,
          },
          signal,
        );
        upload = started.transfer_id;
      },
    );
    const result = await call<Receipt>(
      target,
      "fs.upload.commit",
      { transfer_id: upload },
      signal,
    );
    if (result.sha256 !== info.sha256 || result.size !== info.size)
      throw new NativeTransferError("devices.checksumMismatch");
    committed = true;
    return result;
  } finally {
    if (upload && !committed) await close(target, "upload", upload);
  }
}

export async function downloadNativeFile(
  context: string,
  path: string,
  signal: AbortSignal,
  progress: Progress,
  writer?: {
    write: (data: Uint8Array) => Promise<void>;
    close: () => Promise<void>;
    abort: () => Promise<void>;
  },
): Promise<Blob | null> {
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  try {
    await readNativeFile(
      context,
      path,
      signal,
      progress,
      async (bytes) => {
        if (writer) await writer.write(bytes);
        else chunks.push(new Uint8Array(bytes));
      },
      async (info) => {
        if (!writer && info.size > 256 * CHUNK)
          throw new NativeTransferError("devices.native.browserDownloadLimit");
      },
    );
    await writer?.close();
    return writer
      ? null
      : new Blob(chunks, { type: "application/octet-stream" });
  } catch (error) {
    await writer?.abort();
    throw error;
  }
}
