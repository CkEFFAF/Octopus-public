import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Input,
  Spin,
  Splitter,
  Tag,
} from "antd";
import { ArrowUp, Folder, MoreHorizontal, RefreshCw, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../api/modules/execution";
import type { Device } from "../../api/modules/devices";
import CodeEditor from "../Agent/Workspace/components/CodeEditor";
import { fileTreeIcon } from "../../utils/fileTreeIcon";
import { fileSourcesApi } from "../../api/modules/fileSources";
import { getDocKind } from "../../utils/docKind";
import ResourcePanelContent from "../Chat/components/ResourcePanelContent";
import { decodeEditableText, encodeEditableText } from "./nativeText";
import {
  base64ToBytes,
  bytesToBase64,
  formatBytes,
  nativeParentPath,
  sha256,
} from "./helpers";
import styles from "./NativeDeviceFiles.module.less";
import { apiErrorMessage } from "../../utils/apiError";
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
  agentId,
  threadId,
}: {
  device: Device | ExecutionTarget;
  onError: (error: unknown) => void;
  executionContext?: ExecutionContext;
  initialFilePath?: string;
  agentId?: string;
  threadId?: string;
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
  const [listingState, setListingState] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [listingError, setListingError] = useState("");
  const listingRequest = useRef(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<{
    path: string;
    text: string;
    original: string;
    hash: string;
    bom: boolean;
    eol: string;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<{ path: string; id: string } | null>(
    null,
  );
  const [editingPath, setEditingPath] = useState(false);
  const [transfer, setTransfer] = useState<TransferSelection | null>(null);
  const [contextFailed, setContextFailed] = useState(false);
  const [remoteConflict, setRemoteConflict] = useState<string | null>(null);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 540px)").matches,
  );
  const panelRef = useRef<HTMLDivElement | null>(null);
  const saving = useRef(false);
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const update = () => {
      const width = panel.getBoundingClientRect().width;
      if (width > 0) setNarrow(width <= 540);
    };
    const observer = new ResizeObserver(update);
    observer.observe(panel);
    update();
    return () => observer.disconnect();
  }, []);
  const writable =
    device.permissions.includes("files_write") &&
    !["ask", "plan"].includes(executionContext?.work_mode ?? "agentic");
  const epoch = useRef(0);
  const dirty = !!file && file.text !== file.original;
  const fileRef = useRef(file);
  fileRef.current = file;
  function confirmLeave() {
    return !dirty || window.confirm(t("devices.native.confirmDiscard"));
  }
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      const current = fileRef.current;
      if (current && current.text !== current.original) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);
  const translate = useRef(t);
  translate.current = t;
  const errorHandler = useRef(onError);
  const initialOpened = useRef("");
  errorHandler.current = onError;
  useEffect(() => {
    let disposed = false;
    epoch.current += 1;
    setContext(null);
    setEntries([]);
    setNextOffset(null);
    setListingState("idle");
    setListingError("");
    setFile(null);
    setPreview(null);
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
      const request = ++listingRequest.current;
      const current = () =>
        stamp === epoch.current && request === listingRequest.current;
      setBusy(true);
      setListingState("loading");
      setListingError("");
      if (!offset) {
        setEntries([]);
        setNextOffset(null);
      }
      try {
        const result = await executionApi.call<Listing>(
          context.context_id,
          "fs.list",
          { path, offset },
        );
        if (!current()) return;
        if (!Array.isArray(result.entries) || typeof result.path !== "string")
          throw new Error(translate.current("devices.loadFailed"));
        setEntries((entries) =>
          offset ? [...entries, ...result.entries] : result.entries,
        );
        setDraftPath(result.path);
        setNextOffset(result.next_offset);
        setListingState("success");
      } catch (error) {
        if (current()) {
          setListingState("error");
          setListingError(
            apiErrorMessage(
              error,
              translate.current("devices.loadFailed"),
              translate.current,
            ),
          );
          errorHandler.current(error);
        }
      } finally {
        if (current()) setBusy(false);
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
    if (!confirmLeave()) return;
    if (!entry.is_dir) setDirectoryOpen(false);
    if (entry.is_dir) {
      setFile(null);
      setPreview(null);
      setRemoteConflict(null);
      setPath(entry.path);
      return;
    }
    const stamp = epoch.current;
    setBusy(true);
    setNotice("");
    try {
      if (
        agentId &&
        threadId &&
        ((getDocKind(entry.path) && !/\.(csv|tsv)$/i.test(entry.path)) ||
          /\.(png|jpe?g|webp|gif|svg|bmp|mp4|webm|mov|mkv|mp3|wav|ogg|flac|m4a)$/i.test(
            entry.path,
          ))
      ) {
        const opened = await fileSourcesApi.open(agentId, threadId, {
          kind: "execution",
          context_id: context.context_id,
          path: entry.path,
        });
        if (stamp === epoch.current) {
          setFile(null);
          setPreview({ path: entry.path, id: opened.resource.resource_id });
        }
        return;
      }
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
      const { text, bom, eol } = decodeEditableText(bytes);
      if (stamp === epoch.current) {
        setPreview(null);
        setFile({
          path: result.path,
          text,
          original: text,
          hash: stat.sha256,
          bom,
          eol,
        });
      }
    } catch (error) {
      if (stamp === epoch.current) errorHandler.current(error);
    } finally {
      if (stamp === epoch.current) setBusy(false);
    }
  }
  async function save() {
    if (!context || !file || busy || saving.current) return;
    saving.current = true;
    const stamp = epoch.current;
    const editing = file;
    setBusy(true);
    try {
      const result = await executionApi.call<{ sha256: string }>(
        context.context_id,
        "fs.write",
        {
          path: editing.path,
          data_b64: bytesToBase64(
            encodeEditableText(
              editing.text,
              editing.bom,
              editing.eol,
              editing.original,
            ),
          ),
          expected_sha256: editing.hash,
        },
      );
      if (stamp === epoch.current) {
        setFile((current) =>
          current?.path === editing.path
            ? { ...current, original: editing.text, hash: result.sha256 }
            : current,
        );
        setNotice(t("devices.native.saved"));
        setRemoteConflict(null);
      }
    } catch (error) {
      if (stamp === epoch.current) {
        setNotice(t("devices.native.saveFailedDraft"));
        errorHandler.current(error);
        // Transport errors may be localized or hide the device error text.
        // Compare actual bytes instead of inferring conflicts from a message.
        try {
          const remote = await executionApi.call<Read>(
            context.context_id,
            "fs.read",
            { path: editing.path },
          );
          const bytes = base64ToBytes(remote.data_b64);
          if (
            remote.eof &&
            (await sha256(bytes)) !== editing.hash &&
            stamp === epoch.current
          )
            setRemoteConflict(decodeEditableText(bytes).text);
        } catch {
          // The original save failure remains visible and the draft is intact.
        }
      }
    } finally {
      saving.current = false;
      if (stamp === epoch.current) setBusy(false);
    }
  }
  const directoryContent = (
    <div className={styles.files}>
      {!context &&
        (contextFailed ? (
          <Alert type="error" message={t("devices.loadFailed")} />
        ) : (
          <Spin size="small" />
        ))}
      {context && listingState === "loading" && <Spin size="small" />}
      {context && listingState === "error" && (
        <Alert type="error" message={listingError} />
      )}
      {context && listingState === "success" && !entries.length && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("devices.emptyDirectory")}
        />
      )}
      {entries.map((entry) => (
        <div className={styles.entry} key={entry.path}>
          <button
            className={
              (file?.path ?? preview?.path) === entry.path
                ? styles.selected
                : ""
            }
            disabled={busy || entry.unavailable}
            onClick={() => void open(entry)}
          >
            {entry.is_dir ? <Folder size={16} /> : fileTreeIcon(entry.path, 16)}
            <span>
              {entry.name}
              {entry.is_link && " ↗"}
            </span>
            <small>{entry.is_dir ? "" : formatBytes(entry.size ?? 0)}</small>
          </button>
          {!entry.is_dir && !entry.unavailable && (
            <Dropdown
              trigger={["click"]}
              overlayStyle={{ zIndex: 2100 }}
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
  );
  return (
    <div ref={panelRef} className={styles.panel}>
      <div className={styles.toolbar}>
        {narrow && (
          <Button
            type="text"
            icon={<Folder size={16} />}
            onClick={() => setDirectoryOpen(true)}
            aria-label={t("devices.native.files")}
          />
        )}
        <Button
          aria-label={t("devices.native.parent")}
          icon={<ArrowUp size={15} />}
          disabled={busy || !context}
          onClick={() => {
            if (!confirmLeave()) return;
            setFile(null);
            setPreview(null);
            setPath(nativeParentPath(draftPath, device.platform === "windows"));
          }}
        />
        {editingPath ? (
          <Input
            autoFocus
            onBlur={() => setEditingPath(false)}
            value={draftPath}
            disabled={busy}
            onChange={(e) => setDraftPath(e.target.value)}
            onPressEnter={() => {
              if (confirmLeave()) {
                setFile(null);
                setPreview(null);
                setPath(draftPath);
                setEditingPath(false);
              }
            }}
            aria-label={t("devices.native.path")}
          />
        ) : (
          <button
            className={styles.path}
            title={draftPath}
            onClick={() => setEditingPath(true)}
          >
            {draftPath.replace(/[\\/]/g, " / ")}
          </button>
        )}
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
      {narrow && (
        <Drawer
          classNames={{ body: styles.directoryBody }}
          title={t("devices.native.files")}
          placement="left"
          open={directoryOpen}
          onClose={() => setDirectoryOpen(false)}
          width="min(300px,85vw)"
          getContainer={false}
        >
          {directoryContent}
        </Drawer>
      )}
      <Splitter className={styles.content} layout="horizontal">
        {!narrow && (
          <Splitter.Panel defaultSize={240} min={140} max="50%" collapsible>
            {directoryContent}
          </Splitter.Panel>
        )}
        <Splitter.Panel min={160}>
          <div className={styles.editor}>
            {preview && agentId && threadId ? (
              <ResourcePanelContent
                agentId={agentId}
                threadId={threadId}
                resourceId={preview.id}
              />
            ) : file ? (
              <>
                <div className={styles.fileHeading}>
                  {fileTreeIcon(file.path, 16)}
                  <code title={file.path}>
                    {file.path.split(/[\\/]/).pop()}
                    {dirty ? " •" : ""}
                  </code>
                  <Tag className={styles.encodingTag}>UTF-8</Tag>
                  {!writable && (
                    <Tag title={t("workspace0034.readOnlyFileHint")}>
                      {t("workspace0034.readOnlyFile")}
                    </Tag>
                  )}
                  {agentId && threadId && (
                    <Button
                      size="small"
                      disabled={busy || dirty}
                      onClick={() => {
                        void fileSourcesApi
                          .open(agentId, threadId, {
                            kind: "execution",
                            context_id: context!.context_id,
                            path: file.path,
                          })
                          .then(({ resource }) =>
                            setPreview({
                              path: file.path,
                              id: resource.resource_id,
                            }),
                          )
                          .catch(errorHandler.current);
                      }}
                    >
                      {t("workspace0034.previewAnnotate")}
                    </Button>
                  )}
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() =>
                      void open({
                        path: file.path,
                        name: file.path,
                        is_dir: false,
                      })
                    }
                  >
                    {t("common.refresh")}
                  </Button>
                  <Button
                    icon={<Save size={14} />}
                    size="small"
                    loading={busy}
                    disabled={
                      file.text === file.original ||
                      !writable ||
                      remoteConflict !== null
                    }
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
                {remoteConflict !== null && (
                  <div className={styles.conflict}>
                    <Alert
                      type="warning"
                      message={t("workspace0034.conflictCompare")}
                    />
                    <pre aria-label={t("workspace0034.remoteVersion")}>
                      {remoteConflict}
                    </pre>
                    <Button onClick={() => setRemoteConflict(null)}>
                      {t("common.close")}
                    </Button>
                  </div>
                )}
                <CodeEditor
                  key={`${context?.context_id}:${file.path}`}
                  path={file.path}
                  value={file.text}
                  onSave={() => {
                    if (writable && dirty) void save();
                  }}
                  readOnly={!writable || busy}
                  onChange={(text) =>
                    setFile((current) =>
                      current ? { ...current, text } : current,
                    )
                  }
                />
              </>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("devices.native.pickFile")}
              />
            )}
          </div>
        </Splitter.Panel>
      </Splitter>
    </div>
  );
}
