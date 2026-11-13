import { useEffect, useMemo, useState } from "react";
import { Empty, Popover, Spin, Tooltip } from "antd";
import { FilePen, RefreshCw, Download, ExternalLink, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import Markdown from "../../../components/Markdown/LazyMarkdown";
import { isMarkdownFile } from "../../../utils/textFile";
import { request, requestBlob } from "../../../api/request";
import { message } from "@/utils/antdMessage";
import { executionApi } from "../../../api/modules/execution";
import { useAgent } from "../../../context/AgentContext";
import {
  dockFileBasename,
  isHostAbsolutePath,
  toDockWorkspaceApiPath,
} from "../utils/dockFilePath";
import { changedFileKey } from "../utils/changedFiles";
import type { TurnFileChange } from "../utils/turnFileChanges";
import styles from "./TurnFileChangesModal.module.less";

export default function FileChangesReview({
  files,
  current,
  threadId,
  onOpenFile,
}: {
  files: TurnFileChange[];
  current: TurnFileChange[];
  threadId?: string | null;
  onOpenFile?: (path: string, agentId?: string | null) => void;
}) {
  const { t } = useTranslation();
  const { agents = [] } = useAgent();
  const first = current[0]?.key ?? files[0]?.key;
  const turnAnchor = current[0]?.edits[0]?.id;
  const [selected, setSelected] = useState(first);
  const [refresh, setRefresh] = useState(0);
  const [sourceFile, setSourceFile] = useState<string | null>(null);
  const [narrowPane, setNarrowPane] = useState<"diff" | "current">("diff");
  const [live, setLive] = useState<{
    key: string;
    content?: string;
    error?: string;
  }>({ key: "" });
  // Opening another turn focuses its first changed file, even if the dock was open.
  useEffect(() => setSelected(first), [first, turnAnchor]);
  const file =
    files.find((item) => item.key === selected) ??
    files.find((item) => item.key === first) ??
    files[0];
  const currentKeys = useMemo(
    () =>
      new Set(
        current.map((item) =>
          changedFileKey(item.path, item.agentId, item.deviceId),
        ),
      ),
    [current],
  );
  const source = (item: TurnFileChange) => {
    const expert =
      agents.find((agent) => agent.agent_id === item.agentId)?.name ??
      item.agentId ??
      t("chat.turnChanges.currentExpert");
    return item.deviceId ? `${expert} · ${item.deviceId}` : expert;
  };
  const download = async () => {
    if (!file || file.deviceId) return;
    try {
      const blob = await requestBlob(
        `/agents/${encodeURIComponent(
          file.agentId || "",
        )}/workspace/download?path=${encodeURIComponent(
          toDockWorkspaceApiPath(file.path, file.agentId),
        )}`,
      );
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = dockFileBasename(file.path);
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("workspace.downloadFailed"),
      );
    }
  };
  const {
    key: fileKey,
    path: filePath,
    agentId: fileAgentId,
    deviceId: fileDeviceId,
    contextId: fileContextId,
  } = file ?? {};
  const tooLarge = t("chat.fileReview.tooLarge");
  const missingContext = t("chat.fileReview.missingContext");
  useEffect(() => {
    if (!fileKey || !filePath) return;
    const controller = new AbortController();
    const key = fileKey;
    setLive({ key });
    const load = async () => {
      if (fileDeviceId) {
        if (!fileContextId && !isHostAbsolutePath(filePath))
          throw new Error(missingContext);
        const contextId =
          fileContextId ??
          (
            await executionApi.createContext({
              device_id: fileDeviceId,
              agent_id: fileAgentId,
              thread_id: threadId || undefined,
            })
          ).context_id;
        if (controller.signal.aborted) return;
        const result = await executionApi.call<{
          data_b64: string;
          eof: boolean;
        }>(contextId, "fs.read", { path: filePath }, controller.signal);
        if (!result.eof) throw new Error(tooLarge);
        return new TextDecoder("utf-8", { fatal: true }).decode(
          Uint8Array.from(atob(result.data_b64), (c) => c.charCodeAt(0)),
        );
      }
      const result = await request<{ content: string }>(
        `/agents/${encodeURIComponent(
          fileAgentId || "",
        )}/workspace/file?path=${encodeURIComponent(
          toDockWorkspaceApiPath(filePath, fileAgentId),
        )}`,
        { signal: controller.signal },
      );
      return result.content;
    };
    void load()
      .then((content) => {
        if (!controller.signal.aborted) setLive({ key, content });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setLive({
            key,
            error: error instanceof Error ? error.message : String(error),
          });
      });
    return () => controller.abort();
  }, [
    fileKey,
    filePath,
    fileAgentId,
    fileDeviceId,
    fileContextId,
    threadId,
    refresh,
    tooLarge,
    missingContext,
  ]);
  if (!files.length)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("chat.dockFileListEmpty")}
      />
    );
  return (
    <div className={styles.review}>
      <div className={styles.notice}>
        <span>
          {t("chat.fileReview.summary", {
            count: files.length,
            current: current.length,
          })}
        </span>
        <Tooltip
          title={
            <>
              {t("chat.fileReview.scope", {
                count: files.length,
                current: current.length,
              })}{" "}
              {t("chat.fileReview.liveHint")}
            </>
          }
        >
          <button
            type="button"
            className={styles.info}
            aria-label={t("chat.fileReview.explanation")}
          >
            <Info size={14} />
          </button>
        </Tooltip>
        <div
          className={styles.paneTabs}
          role="tablist"
          aria-label={t("chat.fileReview.view")}
        >
          <button
            type="button"
            role="tab"
            aria-selected={narrowPane === "diff"}
            onClick={() => setNarrowPane("diff")}
          >
            {t("chat.turnChanges.diff")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={narrowPane === "current"}
            onClick={() => setNarrowPane("current")}
          >
            {t("chat.fileReview.fullContent")}
          </button>
        </div>
      </div>
      <div className={styles.layout}>
        <nav className={styles.files} aria-label={t("chat.turnChanges.files")}>
          {files.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={item.key === file?.key}
              className={item.key === file?.key ? styles.selected : ""}
              onClick={() => setSelected(item.key)}
              title={`${item.path} · ${source(item)}`}
            >
              <FilePen size={15} />
              <div className={styles.fileLabel}>
                <span>{dockFileBasename(item.path)}</span>
              </div>
              {currentKeys.has(item.key) && (
                <span
                  className={styles.turnBadge}
                  aria-label={t("chat.fileReview.currentTurn")}
                  title={t("chat.fileReview.currentTurn")}
                />
              )}
            </button>
          ))}
        </nav>
        {file && (
          <section className={styles.details}>
            <div className={styles.path}>
              <Popover
                trigger="click"
                content={
                  <div className={styles.fileInfo}>
                    <div>{file.path}</div>
                    <small>{source(file)}</small>
                  </div>
                }
              >
                <button
                  type="button"
                  className={styles.fileName}
                  aria-label={t("chat.fileReview.details")}
                >
                  <span>{dockFileBasename(file.path)}</span>
                  <Info size={14} />
                </button>
              </Popover>
              {!file.deviceId && (
                <div className={styles.fileActions}>
                  {onOpenFile && (
                    <button
                      type="button"
                      onClick={() => onOpenFile(file.path, file.agentId)}
                      aria-label={t("common.preview")}
                      title={t("common.preview")}
                    >
                      <ExternalLink size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void download()}
                    aria-label={t("common.download")}
                    title={t("common.download")}
                  >
                    <Download size={14} />
                  </button>
                </div>
              )}
            </div>
            <div className={styles.comparison}>
              <section
                className={styles.diffPane}
                aria-label={t("chat.turnChanges.diff")}
                data-active={narrowPane === "diff"}
              >
                <div className={styles.paneTitle}>
                  {t(
                    currentKeys.has(file.key)
                      ? "chat.fileReview.turnDiff"
                      : "chat.fileReview.recordedDiff",
                  )}
                </div>
                {!file.edits.length && (
                  <p className={styles.empty}>
                    {t(
                      file.confirmed
                        ? "chat.turnChanges.unavailable"
                        : "chat.turnChanges.unverified",
                    )}
                  </p>
                )}
                {file.edits.map((edit, index) => (
                  <article key={edit.id} className={styles.edit}>
                    <div className={styles.editTitle}>
                      {t("chat.turnChanges.operation", { number: index + 1 })}
                      {edit.replaceAll && (
                        <span>
                          {typeof edit.occurrences === "number"
                            ? t("chat.turnChanges.replaceAll", {
                                count: edit.occurrences,
                              })
                            : t("chat.turnChanges.replaceAllUnknown")}
                        </span>
                      )}
                    </div>
                    {edit.kind === "replace" && (
                      <>
                        <div className={styles.label}>
                          {t("chat.turnChanges.before")}
                        </div>
                        <pre className={styles.removed}>
                          {edit.before || t("chat.turnChanges.emptyText")}
                        </pre>
                      </>
                    )}
                    <div className={styles.label}>
                      {t(
                        edit.kind === "replace"
                          ? "chat.turnChanges.after"
                          : "chat.turnChanges.written",
                      )}
                    </div>
                    <pre className={styles.added}>
                      {edit.after || t("chat.turnChanges.emptyText")}
                    </pre>
                  </article>
                ))}
              </section>
              <section
                className={styles.currentPane}
                aria-label={t("chat.fileReview.fullContent")}
                data-active={narrowPane === "current"}
              >
                <div className={styles.paneTitle}>
                  {t("chat.fileReview.fullContent")}
                  <div className={styles.paneActions}>
                    {isMarkdownFile(file.path) && (
                      <button
                        type="button"
                        onClick={() =>
                          setSourceFile(
                            sourceFile === file.key ? null : file.key,
                          )
                        }
                      >
                        {t(
                          sourceFile === file.key
                            ? "chat.fileReview.showRendered"
                            : "chat.fileReview.showSource",
                        )}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setRefresh((n) => n + 1)}
                      aria-label={t("common.refresh")}
                      title={t("common.refresh")}
                    >
                      <RefreshCw size={14} />
                    </button>
                  </div>
                </div>
                {live.key !== file.key ||
                (live.content === undefined && !live.error) ? (
                  <Spin />
                ) : live.error ? (
                  <div className={styles.empty} role="status">
                    <p>{t("chat.fileReview.readFailed")}</p>
                    <p>{live.error}</p>
                    {!file.deviceId && onOpenFile && (
                      <button
                        type="button"
                        onClick={() => onOpenFile(file.path, file.agentId)}
                      >
                        {t("common.preview")}
                      </button>
                    )}
                  </div>
                ) : isMarkdownFile(file.path) && sourceFile !== file.key ? (
                  <Markdown
                    content={live.content ?? ""}
                    className={styles.markdownContent}
                  />
                ) : (
                  <pre className={styles.fullContent}>{live.content}</pre>
                )}
              </section>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
