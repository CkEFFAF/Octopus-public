import { useEffect, useState } from "react";
import { Button } from "antd";
import { Download, Eye, Paperclip, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  collaborationApi,
  downloadCollaborationResource,
  verifiedResourceContent,
  type CollaborationResource,
} from "../../../api/modules/collaboration";
import { fileTreeIcon } from "../../../utils/fileTreeIcon";
import { formatBytes } from "../../../utils/embeddingDownload";
import { useCollaboration } from "../hooks/useCollaboration";
import styles from "./ChatDeliverables.module.less";

function ResourceCard({
  agentId,
  threadId,
  resource,
  onOpen,
}: {
  agentId: string;
  threadId: string;
  resource: CollaborationResource;
  onOpen: (resource: CollaborationResource) => void;
}) {
  const { t } = useTranslation();
  const [image, setImage] = useState("");
  const [error, setError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const {
    resource_id: resourceId,
    version,
    size,
    media_type: mediaType,
  } = resource;
  useEffect(() => {
    let active = true;
    let url = "";
    setImage("");
    // Avoid eagerly loading a large image just to render a thumbnail.
    if (
      /^image\/(png|jpeg|gif|webp|avif)$/.test(mediaType) &&
      size <= 8 * 1024 * 1024
    ) {
      void collaborationApi
        .resource(agentId, threadId, resourceId)
        .then((metadata) => {
          if (metadata.version !== version || metadata.size !== size)
            throw new Error("resource_version_mismatch");
          return verifiedResourceContent(agentId, threadId, metadata);
        })
        .then((blob) => {
          if (!active) return;
          url = URL.createObjectURL(blob);
          setImage(url);
        })
        .catch(() => {
          /* The preview button can retry through the resource panel. */
        });
    }
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [agentId, threadId, resourceId, version, size, mediaType]);

  async function download() {
    setDownloading(true);
    setError(false);
    try {
      await downloadCollaborationResource(agentId, threadId, resource);
    } catch {
      setError(true);
    } finally {
      setDownloading(false);
    }
  }
  return (
    <article className={styles.card}>
      <button
        className={styles.preview}
        onClick={() => onOpen(resource)}
        aria-label={t("chat.deliverables.open", { name: resource.name })}
      >
        {image ? (
          <img src={image} alt={resource.name} />
        ) : (
          fileTreeIcon(resource.name, 24)
        )}
      </button>
      <div className={styles.meta}>
        <strong title={resource.name}>{resource.name}</strong>
        <span>{formatBytes(resource.size)}</span>
        {error && <span role="alert">{t("collaboration.resourceError")}</span>}
      </div>
      <div className={styles.actions}>
        <Button
          size="small"
          type="text"
          icon={<Eye size={14} />}
          onClick={() => onOpen(resource)}
          aria-label={t("chat.deliverables.open", { name: resource.name })}
        >
          {t("common.preview")}
        </Button>
        <Button
          size="small"
          loading={downloading}
          icon={<Download size={14} />}
          onClick={() => void download()}
          aria-label={t("chat.flow.downloadFile", { name: resource.name })}
        >
          {t("common.download")}
        </Button>
      </div>
    </article>
  );
}

/** Uses the root thread's authorized artifact list, including child expert results. */
export default function ChatDeliverables({
  agentId,
  threadId,
  onOpen,
}: {
  agentId: string;
  threadId: string;
  onOpen: (resource: CollaborationResource) => void;
}) {
  const { t } = useTranslation();
  const { page, error, refresh } = useCollaboration(agentId, threadId);
  const resources = page.artifacts.filter(
    (resource) =>
      resource.source_kind !== "upload" &&
      resource.publication_state === "published",
  );
  if (!resources.length && !error) return null;
  return (
    <section
      className={styles.deliverables}
      aria-label={t("chat.deliverables.title")}
    >
      <div className={styles.heading}>
        <span className={styles.label}>
          <Paperclip size={16} aria-hidden />
          <strong>{t("chat.deliverables.title")}</strong>
          <span className={styles.count}>{resources.length}</span>
        </span>
        <Button
          size="small"
          type="text"
          icon={<RefreshCw size={14} />}
          onClick={() => void refresh()}
        >
          {t("common.refresh")}
        </Button>
      </div>
      {error && <p role="status">{t("chat.deliverables.refreshFailed")}</p>}
      <div>
        {resources.map((resource) => (
          <ResourceCard
            key={resource.resource_id + resource.version}
            agentId={agentId}
            threadId={threadId}
            resource={resource}
            onOpen={onOpen}
          />
        ))}
      </div>
    </section>
  );
}
