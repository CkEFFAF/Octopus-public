import { useCallback, useState } from "react";
import { Download, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import { downloadAuthFile } from "../../../components/AuthFileDownloadLink";
import {
  isDataUrl,
  needsAuthBlobFetch,
  workspacePathFromAccessUrl,
} from "../../../utils/toolMediaBlocks";
import { getDocKind } from "../../Agent/Workspace/utils/docKind";
import { getMediaKind } from "../../Agent/Workspace/utils/mediaKind";
import { isProbablyText } from "../../Agent/Workspace/utils/fileKind";
import { useChatFilePreview } from "../ChatFilePreviewContext";
import { fileTreeIcon } from "../../../utils/fileTreeIcon";
import styles from "./MessageFileCard.module.less";

import { message as antMessage } from "@/utils/antdMessage";

/** Files the browser can render inline (vs. pure binary blobs). */
function isPreviewable(name: string): boolean {
  return (
    isProbablyText(name) ||
    getMediaKind(name) !== null ||
    getDocKind(name) !== null
  );
}

/** Authenticated download card for chat / tool-result non-image files. */
export function MessageFileCard({
  url,
  filename,
  agentId,
  workspacePath,
}: {
  url: string;
  filename?: string;
  agentId?: string | null;
  workspacePath?: string;
}) {
  const { t } = useTranslation();
  const filePreview = useChatFilePreview();
  const [loading, setLoading] = useState(false);
  const needsAuth = needsAuthBlobFetch(url) || isDataUrl(url);
  const resolvedPath = workspacePath || workspacePathFromAccessUrl(url) || "";
  const label =
    filename || resolvedPath.split(/[\\/]/).pop() || t("chat.flow.file");
  const previewable = Boolean(
    resolvedPath && agentId && isPreviewable(label) && filePreview,
  );

  const handleDownload = useCallback(async () => {
    if (!needsAuth) {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "download";
      a.target = "_blank";
      a.rel = "noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return;
    }
    setLoading(true);
    try {
      await downloadAuthFile(url, { filename });
    } catch {
      antMessage.error(t("chat.downloadFailed", "下载失败，请重试"));
    } finally {
      setLoading(false);
    }
  }, [url, filename, needsAuth, t]);

  const openPreview = useCallback(() => {
    if (previewable && resolvedPath && filePreview) {
      filePreview.openFilePreview(resolvedPath, agentId, "workspace");
    }
  }, [previewable, resolvedPath, filePreview, agentId]);

  return (
    <article className={styles.card} aria-label={label}>
      <span className={styles.icon} aria-hidden>
        {fileTreeIcon(label, 24)}
      </span>
      <div className={styles.meta}>
        {previewable ? (
          <button
            className={styles.name}
            title={label}
            onClick={openPreview}
            type="button"
          >
            {label}
          </button>
        ) : (
          <span className={styles.name} title={label}>
            {label}
          </span>
        )}
        <span className={styles.kind}>
          {label.split(".").length > 1
            ? label.split(".").pop()?.toUpperCase()
            : t("chat.flow.file")}
        </span>
      </div>
      <div className={styles.actions}>
        {previewable && (
          <button
            type="button"
            className={styles.action}
            onClick={openPreview}
            title={t("common.preview")}
            aria-label={t("common.preview")}
          >
            <Eye size={15} strokeWidth={2} />
            <span>{t("common.preview")}</span>
          </button>
        )}
        <button
          type="button"
          className={styles.action}
          onClick={(e) => {
            e.stopPropagation();
            void handleDownload();
          }}
          disabled={loading}
          title={t("common.download")}
          aria-label={t("common.download")}
        >
          <Download size={15} strokeWidth={2} />
          <span>{t("common.download")}</span>
        </button>
      </div>
    </article>
  );
}
