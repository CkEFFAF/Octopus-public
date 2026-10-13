import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Modal,
  Select,
  Spin,
  Tooltip,
} from "antd";
import {
  ChevronDown,
  Columns2,
  FileCode2,
  Folder,
  GitBranch,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../../api/request";
import { showApiError } from "../../../utils/showApiToast";
import styles from "./ChatDockGit.module.less";
import {
  parseDiff,
  pairDiff,
  diffStats,
  decodeGitPath,
  statusFilePath,
} from "../utils/gitDiff";

type Snapshot = {
  available: boolean;
  repositories: string[];
  path?: string;
  status?: string;
  diff?: string;
  staged_diff?: string;
  truncated?: boolean;
  restorable?: { path: string; hash: string }[];
};
type View = "all" | "unstaged" | "staged";
type FileChange = {
  path: string;
  code: string;
  unstaged: string;
  staged: string;
  restore?: { path: string; hash: string };
};

function splitDiff(value: string): Map<string, string> {
  const result = new Map<string, string>();
  let path = "";
  let lines: string[] = [];
  for (const line of value.split("\n")) {
    if (line.startsWith("diff --git ")) {
      if (path) result.set(path, lines.join("\n"));
      const token = line.match(/ ("b\/(?:\\.|[^"])*"|b\/.*)$/)?.[1];
      path = token ? decodeGitPath(token).slice(2) : "";
      lines = [line];
    } else if (path) lines.push(line);
  }
  if (path) result.set(path, lines.join("\n"));
  return result;
}

function parseFiles(snapshot: Snapshot): FileChange[] {
  const unstaged = splitDiff(snapshot.diff ?? "");
  const staged = splitDiff(snapshot.staged_diff ?? "");
  const files = new Map<string, FileChange>();
  for (const line of (snapshot.status ?? "").split("\n").slice(1)) {
    if (line.length < 4) continue;
    const path = statusFilePath(line.slice(3));
    files.set(path, { path, code: line.slice(0, 2), unstaged: "", staged: "" });
  }
  for (const path of new Set([...unstaged.keys(), ...staged.keys()])) {
    if (!files.has(path))
      files.set(path, { path, code: "M", unstaged: "", staged: "" });
  }
  for (const file of files.values()) {
    file.unstaged = unstaged.get(file.path) ?? "";
    file.staged = staged.get(file.path) ?? "";
    file.restore = snapshot.restorable?.find((item) => item.path === file.path);
  }
  return [...files.values()];
}

function DiffLines({ value, split }: { value: string; split: boolean }) {
  const lines = parseDiff(value);
  return (
    <div className={styles.diffCode} role="region" aria-label="Diff">
      {lines.length === 0 ? (
        <pre className={styles.rawDiff}>{value}</pre>
      ) : split ? (
        pairDiff(lines).map((row, index) =>
          row.hunk ? (
            <div key={index} className={styles.hunkHeader}>
              {row.hunk}
            </div>
          ) : (
            <div className={styles.splitRow} key={index}>
              {(["left", "right"] as const).map((side) => {
                const line = row[side];
                return (
                  <div
                    key={side}
                    className={`${styles.splitCell} ${
                      line ? styles[line.kind] ?? "" : styles.absent
                    }`}
                  >
                    <span className={styles.lineNumber}>
                      {side === "left" ? line?.old : line?.next}
                    </span>
                    <span className={styles.codeText}>{line?.text ?? " "}</span>
                  </div>
                );
              })}
            </div>
          ),
        )
      ) : (
        lines.map((line, index) =>
          line.kind === "hunk" ? (
            <div key={index} className={styles.hunkHeader}>
              {line.text}
            </div>
          ) : (
            <div
              key={index}
              className={`${styles.diffLine} ${styles[line.kind] ?? ""}`}
            >
              <span className={styles.lineNumber}>{line.old}</span>
              <span className={styles.lineNumber}>{line.next}</span>
              <span className={styles.codeText}>
                {line.kind === "added"
                  ? "+"
                  : line.kind === "removed"
                  ? "-"
                  : " "}
                {line.text}
              </span>
            </div>
          ),
        )
      )}
    </div>
  );
}

export default function ChatDockGit({ agentId }: { agentId: string }) {
  const { t } = useTranslation();
  const [repository, setRepository] = useState(".");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("all");
  const [split, setSplit] = useState(true);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [restoreTarget, setRestoreTarget] = useState<{
    path: string;
    hash: string;
  } | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [recoveryCopy, setRecoveryCopy] = useState<string | null>(null);

  const refresh = async (selected = repository) => {
    setLoading(true);
    try {
      const result = await request<Snapshot>(
        `/agents/${encodeURIComponent(
          agentId,
        )}/workspace/git?repository=${encodeURIComponent(selected)}`,
        { cache: "no-store" },
      );
      setSnapshot(result);
      if (result.path) setRepository(result.path);
    } catch (error) {
      setSnapshot(null);
      showApiError(error, t("chat.git.loadFailed"), t);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setRepository(".");
    setSelectedPath(null);
    void refresh(".");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  const files = useMemo(
    () => (snapshot ? parseFiles(snapshot) : []),
    [snapshot],
  );
  const visibleFiles = files.filter(
    (file) =>
      file.path.toLowerCase().includes(filter.toLowerCase()) &&
      (view === "all" ||
        (view === "staged"
          ? !!file.staged || file.code[0] !== " "
          : !!file.unstaged || file.code[1] !== " ")),
  );
  const selected =
    visibleFiles.find((file) => file.path === selectedPath) ?? visibleFiles[0];
  const fileGroups = new Map<string, FileChange[]>();
  for (const file of visibleFiles) {
    const directory = file.path.includes("/")
      ? file.path.slice(0, file.path.lastIndexOf("/"))
      : "";
    fileGroups.set(directory, [...(fileGroups.get(directory) ?? []), file]);
  }
  const sections = selected
    ? (["unstaged", "staged"] as const)
        .filter((key) => view === "all" || view === key)
        .filter((key) => selected[key])
        .map((key) => ({ key, value: selected[key] }))
    : [];
  const stats = diffStats(sections.map((section) => section.value).join("\n"));
  const branch = snapshot?.status?.split("\n")[0]?.replace(/^##\s*/, "") ?? "";

  const restore = async () => {
    if (!restoreTarget) return;
    setRestoring(true);
    try {
      const result = await request<{ recovery_copy: string }>(
        `/agents/${encodeURIComponent(agentId)}/workspace/git/restore`,
        {
          method: "POST",
          body: JSON.stringify({
            repository,
            path: restoreTarget.path,
            expected_hash: restoreTarget.hash,
          }),
        },
      );
      setRecoveryCopy(result.recovery_copy);
      setRestoreTarget(null);
      await refresh();
    } catch (error) {
      showApiError(error, t("chat.git.restoreFailed"), t);
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div className={styles.root}>
      <header className={styles.toolbar}>
        <Dropdown
          menu={{
            items: (["all", "unstaged", "staged"] as const).map((key) => ({
              key,
              label: t(`chat.git.view.${key}`),
            })),
            selectedKeys: [view],
            onClick: ({ key }) => {
              setView(key as View);
              setSelectedPath(null);
            },
          }}
          trigger={["click"]}
        >
          <Button type="text" className={styles.viewButton}>
            {t(`chat.git.view.${view}`)} <ChevronDown size={14} />
          </Button>
        </Dropdown>
        <span className={styles.count}>{files.length}</span>
        <span className={styles.spacer} />
        <Tooltip title={t("chat.git.splitView")}>
          <Button
            type="text"
            aria-label={t("chat.git.splitView")}
            aria-pressed={split}
            icon={<Columns2 size={15} />}
            onClick={() => setSplit(!split)}
          />
        </Tooltip>
        {snapshot?.repositories && snapshot.repositories.length > 1 && (
          <Select
            size="small"
            value={repository}
            options={snapshot.repositories.map((path) => ({
              label: path,
              value: path,
            }))}
            onChange={(path) => {
              setRepository(path);
              setSelectedPath(null);
              void refresh(path);
            }}
            className={styles.repositorySelect}
          />
        )}
        <Tooltip title={t("chat.git.serverOnly")}>
          <span className={styles.branch}>
            <GitBranch size={14} />
            {branch || repository}
          </span>
        </Tooltip>
        <Tooltip title={t("chat.git.refresh")}>
          <Button
            type="text"
            icon={<RotateCcw size={15} />}
            aria-label={t("chat.git.refresh")}
            onClick={() => void refresh()}
            disabled={loading}
          />
        </Tooltip>
      </header>
      {recoveryCopy && (
        <Alert
          className={styles.notice}
          type="success"
          showIcon
          message={t("chat.git.recoveryCopy", { path: recoveryCopy })}
          closable
          onClose={() => setRecoveryCopy(null)}
        />
      )}
      {snapshot?.truncated && (
        <Alert
          className={styles.notice}
          type="warning"
          message={t("chat.git.truncated")}
        />
      )}
      {loading ? (
        <div className={styles.center}>
          <Spin />
        </div>
      ) : !snapshot?.available ? (
        <div className={styles.center}>
          <Empty description={t("chat.git.noRepository")} />
        </div>
      ) : files.length === 0 ? (
        <div className={styles.center}>
          <Empty description={t("chat.git.clean")} />
        </div>
      ) : (
        <div className={styles.content}>
          <main className={styles.main}>
            {selected ? (
              <>
                <div className={styles.fileHeader}>
                  <FileCode2 size={16} />
                  <span title={selected.path}>{selected.path}</span>
                  <small className={styles.stats}>
                    <b>+{stats.added}</b>
                    <i>−{stats.removed}</i>
                  </small>
                  {selected.restore && (
                    <Tooltip title={t("chat.git.restore")}>
                      <Button
                        type="text"
                        size="small"
                        aria-label={t("chat.git.restore")}
                        icon={<RotateCcw size={14} />}
                        onClick={() => setRestoreTarget(selected.restore!)}
                      />
                    </Tooltip>
                  )}
                </div>
                {sections.length ? (
                  <div className={styles.diffSections}>
                    {sections.map((section) => (
                      <section key={section.key}>
                        <div className={styles.sectionLabel}>
                          {t(`chat.git.view.${section.key}`)}
                        </div>
                        <DiffLines value={section.value} split={split} />
                      </section>
                    ))}
                  </div>
                ) : (
                  <div className={styles.noDiff}>{t("chat.git.noDiff")}</div>
                )}
              </>
            ) : (
              <div className={styles.center}>
                <Empty description={t("chat.git.noDiff")} />
              </div>
            )}
          </main>
          <aside className={styles.sidebar}>
            <div className={styles.sidebarTitle}>
              {t("chat.git.files")} <span>{visibleFiles.length}</span>
            </div>
            <input
              className={styles.search}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder={t("chat.git.filterFiles")}
              aria-label={t("chat.git.filterFiles")}
            />
            <div className={styles.fileList}>
              {[...fileGroups].map(([directory, group]) => (
                <div key={directory || "."}>
                  {directory && (
                    <div className={styles.folderItem}>
                      <Folder size={13} />
                      <span title={directory}>{directory}</span>
                    </div>
                  )}
                  {group.map((file) => (
                    <button
                      type="button"
                      key={file.path}
                      className={`${styles.fileItem} ${
                        file.path === selected?.path ? styles.active : ""
                      }`}
                      onClick={() => setSelectedPath(file.path)}
                      title={file.path}
                    >
                      <span className={styles.fileStatus}>
                        {file.code.trim() || "M"}
                      </span>
                      <span className={styles.fileName}>
                        {file.path.split("/").at(-1)}
                      </span>
                      <small className={styles.stats}>
                        <b>
                          +{diffStats(file.unstaged + "\n" + file.staged).added}
                        </b>
                        <i>
                          −
                          {
                            diffStats(file.unstaged + "\n" + file.staged)
                              .removed
                          }
                        </i>
                      </small>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
      <Modal
        open={restoreTarget !== null}
        title={t("chat.git.restore")}
        onCancel={() => setRestoreTarget(null)}
        onOk={() => void restore()}
        okText={t("chat.git.restore")}
        confirmLoading={restoring}
      >
        {t("chat.git.restoreConfirm", { path: restoreTarget?.path })}
      </Modal>
    </div>
  );
}
