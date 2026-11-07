import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { uploadFile, type UploadResponse } from "../../../api/modules/upload";
import { useChatAttachments } from "./useChatAttachments";

vi.mock("../../../api/modules/upload", () => ({ uploadFile: vi.fn() }));
vi.mock("../../../hooks/useServerUploadLimit", () => ({
  useServerUploadLimit: () => ({ maxUploadBytes: 100000, maxUploadMb: 1 }),
}));
afterEach(() => vi.resetAllMocks());
function response(file: File): UploadResponse {
  return {
    path: "inbound/" + file.name,
    workspace_path: "inbound/" + file.name,
    filename: file.name,
    media_type: file.type,
    url: "/file",
    access_url: "/file",
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it("sends ready attachments without cancelling an unfinished upload", async () => {
  const pending = deferred<UploadResponse>();
  const one = new File(["a"], "ready.pdf");
  const two = new File(["b"], "pending.pdf");
  vi.mocked(uploadFile).mockImplementation((_agent, file) =>
    file === one ? Promise.resolve(response(file)) : pending.promise,
  );
  const { result } = renderHook(() => useChatAttachments("agent", "thread"));
  await act(async () => {
    void result.current.processFiles([one, two]);
  });
  const sent = result.current.attachments;
  act(() => result.current.consumeAttachments(sent));
  expect(result.current.uploading).toBe(true);
  expect(result.current.attachments).toEqual([]);
  await act(async () => pending.resolve(response(two)));
  expect(result.current.attachments.map((file) => file.filename)).toEqual([
    "pending.pdf",
  ]);
});

it("retains successful files and retries only the failed file", async () => {
  const one = new File(["a"], "one.pdf");
  const two = new File(["b"], "two.zip");
  vi.mocked(uploadFile).mockImplementation(async (_agent, file) => {
    if (file === two) throw new Error("offline");
    return response(file);
  });
  const { result } = renderHook(() => useChatAttachments("agent", "thread"));
  await act(async () => result.current.processFiles([one, two]));
  expect(result.current.attachments.map((item) => item.filename)).toEqual([
    "one.pdf",
  ]);
  expect(result.current.uploads[0]).toMatchObject({
    filename: "two.zip",
    status: "failed",
  });
  vi.mocked(uploadFile).mockImplementation(async (_agent, file) =>
    response(file),
  );
  act(() => result.current.retryUpload(result.current.uploads[0].id));
  await waitFor(() => expect(result.current.attachments).toHaveLength(2));
  expect(
    vi.mocked(uploadFile).mock.calls.filter((call) => call[1] === one),
  ).toHaveLength(1);
});

it("keeps uploading while another batch is pending and waits for the server at 100 percent", async () => {
  const first = deferred<UploadResponse>();
  const second = deferred<UploadResponse>();
  const a = new File(["a"], "a.pdf");
  const b = new File(["b"], "b.zip");
  vi.mocked(uploadFile).mockImplementation((_agent, file, options) => {
    options?.onProgress?.(100);
    return file === a ? first.promise : second.promise;
  });
  const { result } = renderHook(() => useChatAttachments("agent", "thread"));
  act(() => {
    void result.current.processFiles([a]);
    void result.current.processFiles([b]);
  });
  expect(result.current.uploading).toBe(true);
  expect(result.current.attachments).toHaveLength(0);
  expect(result.current.uploads.every((item) => item.percent === 100)).toBe(
    true,
  );
  await act(async () => first.resolve(response(a)));
  expect(result.current.uploading).toBe(true);
  await act(async () => second.resolve(response(b)));
  expect(result.current.uploading).toBe(false);
});

it("aborts on thread changes and ignores a late server reply", async () => {
  const pending = deferred<UploadResponse>();
  const file = new File(["a"], "old.pdf");
  let signal: AbortSignal | undefined;
  vi.mocked(uploadFile).mockImplementation((_agent, _file, options) => {
    signal = options?.signal;
    return pending.promise;
  });
  const { result, rerender } = renderHook(
    ({ thread }) => useChatAttachments("agent", thread),
    { initialProps: { thread: "a" } },
  );
  act(() => {
    void result.current.processFiles([file]);
  });
  rerender({ thread: "b" });
  expect(signal?.aborted).toBe(true);
  await act(async () => pending.resolve(response(file)));
  expect(result.current.attachments).toEqual([]);
  expect(result.current.uploads).toEqual([]);
});

it("cancels one pending upload and ignores completion without cancelling the other", async () => {
  const a = new File(["a"], "a.pdf");
  const b = new File(["b"], "b.pdf");
  const first = deferred<UploadResponse>();
  const second = deferred<UploadResponse>();
  vi.mocked(uploadFile).mockImplementation((_agent, file) =>
    file === a ? first.promise : second.promise,
  );
  const { result } = renderHook(() => useChatAttachments("agent", "thread"));
  act(() => {
    void result.current.processFiles([a, b]);
  });
  act(() => result.current.cancelUpload(result.current.uploads[0].id));
  expect(result.current.uploading).toBe(true);
  await act(async () => {
    first.resolve(response(a));
    second.resolve(response(b));
  });
  expect(result.current.attachments.map((item) => item.filename)).toEqual([
    "b.pdf",
  ]);
});
