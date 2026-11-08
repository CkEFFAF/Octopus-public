import type { ChatMessage } from "../hooks/useChat";
import { canonicalizeDockFilePath } from "./dockFilePath";

export interface RecordedFileEdit {
  id: string;
  kind: "replace" | "write";
  before?: string;
  after: string;
  replaceAll?: boolean;
  occurrences?: number;
}
export interface TurnFileChange {
  key: string;
  path: string;
  agentId?: string;
  deviceId?: string;
  contextId?: string;
  confirmed: boolean;
  edits: RecordedFileEdit[];
}

interface FileRecord {
  path: string;
  deviceId?: string;
  contextId?: string;
  completed: boolean;
  edit?: RecordedFileEdit;
}
const records = new WeakMap<ChatMessage, FileRecord | null>();
function fileRecord(message: ChatMessage): FileRecord | null {
  if (records.has(message)) return records.get(message)!;
  const record = parseFileRecord(message);
  records.set(message, record);
  return record;
}
function parseFileRecord(message: ChatMessage): FileRecord | null {
  const tool = message.toolData;
  const name = tool?.name?.split("/").pop()?.toLowerCase();
  if (
    !name ||
    ![
      "write_file",
      "edit_file",
      "send_file",
      "send_file_to_user",
      "device_run",
      "device_operation_get",
    ].includes(name)
  )
    return null;
  const input = object(tool?.arguments);
  const output = object(tool?.output);
  const device = name === "device_run" || name === "device_operation_get";
  const action = output.action ?? input.action;
  if (device && action !== "fs.write" && action !== "fs.edit") return null;
  const args = device ? object(output.params ?? input.params) : input;
  const rawPath = args.file_path ?? args.path ?? args.filepath ?? args.filename;
  if (typeof rawPath !== "string" || !rawPath.trim()) return null;
  const context = object(output.context);
  const deviceId = device
    ? output.device_id ?? context.device_id ?? input.device_id
    : undefined;
  const result: FileRecord = {
    path: rawPath.trim(),
    deviceId: typeof deviceId === "string" ? deviceId : undefined,
    contextId:
      typeof context.context_id === "string" ? context.context_id : undefined,
    completed: false,
  };
  if (
    name.startsWith("send_file") ||
    message.status === "streaming" ||
    message.status === "error" ||
    message.errorInfo ||
    tool?.errorCode ||
    (tool?.returnCode !== undefined && tool.returnCode !== 0) ||
    tool?.output === undefined ||
    output.error ||
    output.is_error === true ||
    output.status === "failed" ||
    /^Error(?:\s|:)/i.test(tool.output)
  )
    return result;
  if (device && output.status !== "completed") return result;
  result.completed = true;
  const id =
    device && typeof output.operation_id === "string"
      ? output.operation_id
      : message.id;
  if (
    (name === "edit_file" || action === "fs.edit") &&
    typeof args.old_string === "string" &&
    typeof args.new_string === "string"
  ) {
    const receipt = device ? object(output.result) : output;
    result.edit = {
      id,
      kind: "replace",
      before: args.old_string,
      after: args.new_string,
      replaceAll: args.replace_all === true,
      occurrences:
        typeof receipt.occurrences === "number"
          ? receipt.occurrences
          : undefined,
    };
  } else if (name === "write_file" || action === "fs.write") {
    let content = args.content;
    if (content === undefined && typeof args.data_b64 === "string") {
      try {
        content = new TextDecoder("utf-8", { fatal: true }).decode(
          Uint8Array.from(atob(args.data_b64), (char) => char.charCodeAt(0)),
        );
      } catch {
        /* Binary or incomplete historical content has no textual diff. */
      }
    }
    if (typeof content === "string")
      result.edit = { id, kind: "write", after: content };
  }
  return result;
}

function object(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      return object(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Only the selected answer's persisted write/edit calls establish changes.
 * Never compare against the current filesystem or another turn's file list.
 */
export function collectTurnFileChanges(
  messages: ChatMessage[],
  agentId?: string | null,
): TurnFileChange[] {
  const files = new Map<string, TurnFileChange>();
  const observed = new Set<string>();
  const identity = (path: string, owner?: string, device?: string) =>
    JSON.stringify([
      owner ?? "",
      device ?? "",
      canonicalizeDockFilePath(path, owner),
    ]);
  for (const message of messages) {
    const record = fileRecord(message);
    if (!record) continue;
    const { path, deviceId } = record;
    const owner = message.speakerAgentId?.trim() || agentId || undefined;
    const key = identity(path, owner, deviceId);
    observed.add(key);
    observed.add(identity(path, owner));
    if (!record.completed) continue;
    let file = files.get(key);
    if (!file) {
      file = {
        key,
        path,
        agentId: owner,
        deviceId,
        contextId: record.contextId,
        confirmed: true,
        edits: [],
      };
      files.set(key, file);
    }
    file.contextId = record.contextId ?? file.contextId;
    if (record.edit && !file.edits.some((edit) => edit.id === record.edit!.id))
      file.edits.push(record.edit);
  }
  for (const message of messages) {
    const owner = message.speakerAgentId?.trim() || agentId || undefined;
    for (const path of message.editedFiles ?? []) {
      if (!path.trim()) continue;
      const key = identity(path, owner);
      if (!observed.has(key) && !files.has(key))
        files.set(key, {
          key,
          path,
          agentId: owner,
          confirmed: false,
          edits: [],
        });
    }
  }
  return [...files.values()];
}
