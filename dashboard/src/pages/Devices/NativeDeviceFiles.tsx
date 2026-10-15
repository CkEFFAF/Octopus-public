import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Dropdown, Empty, Input, Spin, Tag } from "antd";
import {
  ArrowUp,
  File,
  Folder,
  MoreHorizontal,
  RefreshCw,
  Save,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../api/modules/execution";
import type { Device } from "../../api/modules/devices";
import { base64ToBytes, bytesToBase64, formatBytes, sha256 } from "./helpers";
import styles from "./NativeDeviceFiles.module.less";
import NativeFileTransfers, {
  type TransferSelection,
} from "./NativeFileTransfers";

interface Entry {
  name: string;
  path: string;
  is_dir: boolean;
  is_link?: boolean;
  size?: number;
  unavailable?: boolean;
}
interface Listing {
  path: string;
  entries: Entry[];
  next_offset: number | null;
}
interface Read {
  path: string;
  data_b64: string;
  eof: boolean;
  size: number;
}

export default function NativeDeviceFiles({
  device,
  onError,
  executionContext,
  initialFilePath,
}: {
  device: Device | ExecutionTarget;
  onError: (error: unknown) => void;
  executionContext?: ExecutionContext;
  initialFilePath?: string;
}) {
  const { t } = useTranslation();
  const [context, setContext] = useState<ExecutionContext | null>(null);
  const [path, setPath] = useState(
    executionContext?.working_dir ??
      device.working_dir ??
      device.runtime?.working_dir ??
      ".",
  );
  const [draftPath, setDraftPath] = useState(path);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<{
    path: string;
    text: string;
    original: string;
    hash: string;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [transfer, setTransfer] = useState<TransferSelection | null>(null);
  const [contextFailed, setContextFailed] = useState(false);
  const writable =
    device.permissions.includes("files_write") &&
    !["ask", "plan"].includes(executionContext?.work_mode ?? "agentic");
  const epoch = useRef(0);
  const errorHandler = useRef(onError);
  const initialOpened = useRef("");
  errorHandler.current = onError;
  useEffect(() => {
    let disposed = false;
    epoch.current += 1;
    setContext(null);
    setFile(null);
    setTransfer(null);
    setContextFailed(false);
    void (
      executionContext
        ? Promise.resolve(executionContext)
        : executionApi.createContext(
            device.device_id
              ? { device_id: device.device_id }
              : { target_kind: "local" },
          )
    )
      .then((value) => {
        if (!disposed) setContext(value);
      })
      .catch((error) => {
        if (!disposed) {
          setContextFailed(true);
          errorHandler.current(error);
        }
      });
    return () => {
      disposed = true;
      epoch.current += 1;
    };
  }, [
    device.device_id,
    device.policy_revision,
    device.grant_version,
    executionContext,
  ]);
  const load = useCallback(
    async (offset = 0) => {
      if (!context) return;
      const stamp = epoch.current;
      setBusy(true);
      try {
        const result = await executionApi.call<Listing>(
          context.context_id,
          "fs.list",
          { path, offset },
        );
        if (stamp !== epoch.current) return;
        setEntries((current) =>
          offset ? [...current, ...result.entries] : result.entries,
        );
        setDraftPath(result.path);
        setNextOffset(result.next_offset);
      } catch (error) {
        if (stamp === epoch.current) errorHandler.current(error);
      } finally {
        if (stamp === epoch.current) setBusy(false);
      }
    },
    [context, path],
  );
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!context || !initialFilePath) return;
    const key = `${context.context_id}:${initialFilePath}`;
    if (initialOpened.current === key) return;
    initialOpened.current = key;
    const separator = Math.max(
      initialFilePath.lastIndexOf("/"),
      initialFilePath.lastIndexOf("\\"),
    );
    setPath(separator >= 0 ? initialFilePath.slice(0, separator + 1) : ".");
    void open({ path: initialFilePath, name: initialFilePath, is_dir: false });
    // Only initialize once; user edits and navigation must not reopen the file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, initialFilePath]);
  async function open(entry: Entry) {
    if (!context || busy || entry.unavailable) return;
    if (entry.is_dir) {
      setPath(entry.path);
      return;
    }
    if (file && file.text !== file.original) {
      setNotice(t("devices.native.unsaved"));
      return;
    }
    const stamp = epoch.current;
    setBusy(true);
    setNotice("");
    try {
      const stat = await executionApi.call<{
        sha256: string | null;
        size: number;
      }>(context.context_id, "fs.stat", { path: entry.path });
      if (!stat.sha256 || stat.size > 1048576) {
        if (stamp === epoch.current) setNotice(t("devices.native.inlineLimit"));
        return;
      }
      const result = await executionApi.call<Read>(
        context.context_id,
        "fs.read",
        { path: entry.path },
      );
      const bytes = base64ToBytes(result.data_b64);
      if (!result.eof) {
        if (stamp === epoch.current) setNotice(t("devices.native.inlineLimit"));
        return;
      }
      if ((await sha256(bytes)) !== stat.sha256)
        throw new Error(t("devices.native.changedDuringRead"));
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (stamp === epoch.current)
        setFile({ path: result.path, text, original: text, hash: stat.sha256 });
    } catch (error) {
      if (stamp === epoch.current) errorHandler.current(error);
    } finally {
      if (stamp === epoch.current) setBusy(false);
    }
  }
  async function save() {
    if (!context || !file || busy) return;
    const stamp = epoch.current;
    const editing = file;
    setBusy(true);
    try {
      const result = await executionApi.call<{ sha256: string }>(
        context.context_id,
        "fs.write",
        {
          path: editing.path,
          data_b64: bytesToBase64(new TextEncoder().encode(editing.text)),
          expected_sha256: editing.hash,
        },
      );
      if (stamp === epoch.current) {
        setFile({ ...editing, original: editing.text, hash: result.sha256 });
        setNotice(t("devices.native.saved"));
      }
    } catch (error) {
      if (stamp === epoch.current) errorHandler.current(error);
    } finally {
      if (stamp === epoch.current) setBusy(false);
    }
  }
  return (
    <div className={styles.panel}>
      <header>
        <Tag>{device.name}</Tag>
        <span>{t("devices.native.hint")}</span>
      </header>
      <div className={styles.toolbar}>
        <Button
          aria-label={t("devices.native.parent")}
          icon={<ArrowUp size={15} />}
          disabled={busy || !context}
          onClick={() =>
            setPath(
              device.platform === "windows"
                ? `${draftPath.replace(/[\\/]$/, "")}\\..`
                : `${draftPath.replace(/\/$/, "")}/..`,
            )
          }
        />
        <Input
          value={draftPath}
          disabled={busy}
          onChange={(e) => setDraftPath(e.target.value)}
          onPressEnter={() => setPath(draftPath)}
          aria-label={t("devices.native.path")}
        />
        <Button
          disabled={busy || !context}
          onClick={() => {
            if (draftPath === path) void load();
            else setPath(draftPath);
          }}
        >
          {t("devices.native.go")}
        </Button>
        <Button
          aria-label={t("common.refresh")}
          icon={<RefreshCw size={15} />}
          disabled={busy || !context}
          onClick={() => void load()}
        />
        {context && (
          <NativeFileTransfers
            key={context.context_id}
            context={context}
            directory={path}
            writable={writable}
            selection={transfer}
            clearSelection={() => setTransfer(null)}
            onError={onError}
            onChanged={() => void load()}
          />
        )}
      </div>
      {notice && (
        <Alert
          type="info"
          message={notice}
          closable
          onClose={() => setNotice("")}
        />
      )}
      <div className={styles.content}>
        <div className={styles.files}>
          {!context &&
            (contextFailed ? (
              <Alert type="error" message={t("devices.loadFailed")} />
            ) : (
              <Spin size="small" />
            ))}
          {context && !busy && !entries.length && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("devices.emptyDirectory")}
            />
          )}
          {entries.map((entry) => (
            <div className={styles.entry} key={entry.path}>
              <button
                className={file?.path === entry.path ? styles.selected : ""}
                disabled={busy || entry.unavailable}
                onClick={() => void open(entry)}
              >
                {entry.is_dir ? <Folder size={16} /> : <File size={16} />}
                <span>
                  {entry.name}
                  {entry.is_link && " ↗"}
                </span>
                <small>
                  {entry.is_dir ? "" : formatBytes(entry.size ?? 0)}
                </small>
              </button>
              {!entry.is_dir && !entry.unavailable && (
                <Dropdown
                  trigger={["click"]}
                  menu={{
                    items: [
                      { key: "download", label: t("devices.download") },
                      { key: "copy", label: t("devices.native.copyTo") },
                    ],
                    onClick: ({ key }) =>
                      setTransfer({
                        ...entry,
                        action: key as "download" | "copy",
                      }),
                  }}
                >
                  <Button
                    type="text"
                    size="small"
                    aria-label={t("devices.native.fileActions", {
                      name: entry.name,
                    })}
                    icon={<MoreHorizontal size={15} />}
                  />
                </Dropdown>
              )}
            </div>
          ))}
          {nextOffset != null && (
            <Button loading={busy} onClick={() => void load(nextOffset)}>
              {t("devices.native.more")}
            </Button>
          )}
        </div>
        <div className={styles.editor}>
          {file ? (
            <>
              <div className={styles.fileHeading}>
                <code title={file.path}>{file.path}</code>
                <Button
                  icon={<Save size={14} />}
                  size="small"
                  loading={busy}
                  disabled={file.text === file.original || !writable}
                  onClick={() => void save()}
                >
                  {t("devices.native.save")}
                </Button>
              </div>
              {file.text !== file.original && (
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() => setFile({ ...file, text: file.original })}
                >
                  {t("devices.native.discard")}
                </Button>
              )}
              <Input.TextArea
                value={file.text}
                disabled={busy}
                readOnly={!writable}
                onChange={(e) => setFile({ ...file, text: e.target.value })}
                spellCheck={false}
              />
            </>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("devices.native.pickFile")}
            />
          )}
        </div>
      </div>
    </div>
  );
}
