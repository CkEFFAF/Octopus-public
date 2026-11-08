import { useState } from "react";
import { Modal } from "antd";
import { FilePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TurnFileChange } from "../utils/turnFileChanges";
import { dockFileBasename } from "../utils/dockFilePath";
import { useAgent } from "../../../context/AgentContext";
import styles from "./TurnFileChangesModal.module.less";

export default function TurnFileChangesModal({
  files,
  onClose,
}: {
  files: TurnFileChange[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { agents = [] } = useAgent();
  const source = (item: TurnFileChange) => {
    const expert =
      agents.find((agent) => agent.agent_id === item.agentId)?.name ??
      item.agentId ??
      t("chat.turnChanges.currentExpert");
    return t(
      item.deviceId
        ? "chat.turnChanges.deviceSource"
        : "chat.turnChanges.expertSource",
      { expert, device: item.deviceId },
    );
  };
  const [selected, setSelected] = useState(files[0]?.key);
  const file = files.find((item) => item.key === selected) ?? files[0];
  return (
    <Modal
      open
      centered
      title={t("chat.turnChanges.title", { count: files.length })}
      onCancel={onClose}
      footer={null}
      width="min(1040px, calc(100vw - 24px))"
      destroyOnHidden
    >
      <p className={styles.notice}>{t("chat.turnChanges.scope")}</p>
      <div className={styles.layout}>
        <nav className={styles.files} aria-label={t("chat.turnChanges.files")}>
          {files.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={file?.key === item.key}
              className={file?.key === item.key ? styles.selected : ""}
              onClick={() => setSelected(item.key)}
              title={`${item.path} · ${source(item)}`}
            >
              <FilePen size={15} />
              <div className={styles.fileLabel}>
                <span>{dockFileBasename(item.path)}</span>
                <small>{source(item)}</small>
              </div>
            </button>
          ))}
        </nav>
        <section
          className={styles.details}
          aria-label={t("chat.turnChanges.diff")}
        >
          {file && (
            <>
              <div className={styles.path}>
                {file.path}
                <small>{source(file)}</small>
              </div>
              {file.edits.length === 0 && (
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
                  {edit.kind === "replace" ? (
                    <>
                      <div className={styles.label}>
                        {t("chat.turnChanges.before")}
                      </div>
                      <pre className={styles.removed}>
                        {edit.before || t("chat.turnChanges.emptyText")}
                      </pre>
                      <div className={styles.label}>
                        {t("chat.turnChanges.after")}
                      </div>
                      <pre className={styles.added}>
                        {edit.after || t("chat.turnChanges.emptyText")}
                      </pre>
                    </>
                  ) : (
                    <>
                      <div className={styles.label}>
                        {t("chat.turnChanges.written")}
                      </div>
                      <pre className={styles.added}>
                        {edit.after || t("chat.turnChanges.emptyText")}
                      </pre>
                    </>
                  )}
                </article>
              ))}
            </>
          )}
        </section>
      </div>
    </Modal>
  );
}
