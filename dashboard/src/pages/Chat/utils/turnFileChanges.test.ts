import { expect, it } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { collectTurnFileChanges } from "./turnFileChanges";

const call = (
  id: string,
  path: string,
  extra: Partial<ChatMessage> = {},
): ChatMessage => ({
  id,
  role: "assistant",
  content: "",
  timestamp: 1,
  status: "done",
  toolData: {
    name: "edit_file",
    arguments: JSON.stringify({
      file_path: path,
      old_string: `before ${id}`,
      new_string: `after ${id}`,
    }),
    output: '{"occurrences":1}',
  },
  ...extra,
});
it("keeps this answer's file list and replacements independent of previous answers", () => {
  const earlier = [call("old-a", "a.py"), call("old-b", "b.py")];
  const current = [call("new", "b.py")];
  expect(collectTurnFileChanges(earlier)).toHaveLength(2);
  const files = collectTurnFileChanges(current);
  expect(files.map((file) => file.path)).toEqual(["b.py"]);
  expect(files[0].edits).toMatchObject([
    { before: "before new", after: "after new" },
  ]);
});
it("preserves repeated operations, replace-all receipts and distinct expert owners", () => {
  const all = call("all", "same.py", {
    toolData: {
      name: "ns/edit_file",
      arguments: JSON.stringify({
        path: "same.py",
        old_string: "x",
        new_string: "",
        replace_all: true,
      }),
      output: '{"occurrences":3}',
    },
  });
  const files = collectTurnFileChanges(
    [
      call("a", "same.py"),
      all,
      call("peer", "same.py", { speakerAgentId: "peer" }),
    ],
    "host",
  );
  expect(files).toHaveLength(2);
  expect(files[0].edits).toHaveLength(2);
  expect(files[0].edits[1]).toMatchObject({
    after: "",
    replaceAll: true,
    occurrences: 3,
  });
  expect(files[1].agentId).toBe("peer");
});
it("does not turn delivery, attachments, failed or pending writes into completed changes", () => {
  const failed = call("failed", "failed.py", {
    status: "error",
    editedFiles: ["failed.py"],
  });
  const pending = call("pending", "pending.py", {
    status: "streaming",
    editedFiles: ["pending.py"],
  });
  const send = call("send", "send.png", {
    editedFiles: ["send.png"],
    toolData: {
      name: "send_file",
      arguments: '{"file_path":"send.png"}',
      output: "sent",
    },
  });
  const dataError = call("error", "error.py", {
    toolData: {
      name: "write_file",
      arguments: '{"file_path":"error.py","content":"bad"}',
      output: '{"error":"denied"}',
    },
    editedFiles: ["error.py"],
  });
  const user: ChatMessage = {
    id: "upload",
    role: "user",
    timestamp: 1,
    content: "",
    attachments: [{ kind: "file", url: "/x", workspacePath: "upload.py" }],
  };
  expect(
    collectTurnFileChanges([failed, pending, send, dataError, user]),
  ).toEqual([]);
});
it("retains path-only historical evidence without inventing before or after text", () => {
  const files = collectTurnFileChanges([
    {
      id: "history",
      role: "assistant",
      timestamp: 1,
      content: "done",
      editedFiles: ["old.md"],
    },
  ]);
  expect(files).toMatchObject([{ path: "old.md", edits: [] }]);
});
it("records the content of a successful write", () => {
  const files = collectTurnFileChanges([
    call("write", "new.md", {
      toolData: {
        name: "write_file",
        arguments: '{"path":"new.md","content":"# Report"}',
        output: '{"path":"new.md"}',
      },
    }),
  ]);
  expect(files[0].edits).toMatchObject([{ kind: "write", after: "# Report" }]);
});
it("does not label an ambiguous team path stamp as a confirmed edit", () => {
  const result = collectTurnFileChanges([
    {
      id: "team-final",
      role: "assistant",
      timestamp: 1,
      content: "",
      editedFiles: ["delivered-or-failed.md"],
    },
  ]);
  expect(result[0].confirmed).toBe(false);
  expect(result[0].edits).toEqual([]);
});
it("requires a completed device receipt and keeps identical paths on different devices separate", () => {
  const operation = (id: string, device_id: string, status: string) =>
    call(id, "ignored", {
      toolData: {
        name: "device_operation_get",
        arguments: JSON.stringify({ operation_id: id }),
        output: JSON.stringify({
          operation_id: id,
          device_id,
          action: "fs.edit",
          params: {
            path: "/project/a.py",
            old_string: "old",
            new_string: "new",
          },
          status,
          result: { occurrences: 1 },
        }),
      },
    });
  const result = collectTurnFileChanges([
    operation("pending", "one", "queued"),
    operation("done", "one", "completed"),
    operation("done", "one", "completed"),
    operation("other", "two", "completed"),
  ]);
  expect(result).toHaveLength(2);
  expect(result[0]).toMatchObject({
    deviceId: "one",
    confirmed: true,
    edits: [{ before: "old", after: "new" }],
  });
  expect(result[0].edits).toHaveLength(1);
  expect(result[1].deviceId).toBe("two");
});
it("does not reparse a completed file's large arguments on later text tokens", () => {
  const message = call("large", "a.py");
  const original = JSON.parse;
  let parses = 0;
  JSON.parse = (...args) => {
    parses++;
    return original(...args);
  };
  try {
    collectTurnFileChanges([message]);
    const count = parses;
    collectTurnFileChanges([
      message,
      { id: "text", role: "assistant", timestamp: 1, content: "more" },
    ]);
    expect(parses).toBe(count);
  } finally {
    JSON.parse = original;
  }
});
