import { lazy, Suspense, useEffect, useState } from "react";
import { Button, Image, Modal } from "antd";
import { Download, Paperclip, RefreshCw } from "lucide-react";
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
import {
  DELIVERABLE_KINDS,
  DELIVERY_PAGE_SIZE,
  deliverableKind,
  type DeliverableKind,
} from "../utils/deliverableFiles";
import styles from "./ChatDeliverables.module.less";
const ResourcePanelContent = lazy(() => import("./ResourcePanelContent"));

function ResourceCard({
  agentId,
  threadId,
  resource,
  onOpen,
  overview = false,
}: {
  agentId: string;
  threadId: string;
  resource: CollaborationResource;
  onOpen: (resource: CollaborationResource) => void;
  overview?: boolean;
}) {
  const { t } = useTranslation();
  const [image, setImage] = useState("");
  const [error, setError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const {
    resource_id: resourceId,
    version,
    size,
    media_type: mediaType,
  } = resource;
  const dot = resource.name.lastIndexOf(".");
  const stem = dot > 0 ? resource.name.slice(0, dot) : resource.name;
  const extension = dot > 0 ? resource.name.slice(dot) : "";
  useEffect(() => {
    let active = true;
    let url = "";
    setImage("");
    setPreviewOpen(false);
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
          /* Clicking the icon can retry through the resource panel. */
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
  function preview() {
    if (image) setPreviewOpen(true);
    else onOpen(resource);
  }
  return (
    <>
      <article
        className={`${styles.card} ${overview ? styles.imageOverviewCard : ""}`}
      >
        <button
          className={styles.preview}
          onClick={preview}
          aria-label={t("chat.deliverables.open", { name: resource.name })}
          title={t("chat.deliverables.open", { name: resource.name })}
        >
          {image ? (
            <img src={image} alt={resource.name} />
          ) : (
            fileTreeIcon(resource.name, 24)
          )}
        </button>
        <div className={styles.meta}>
          <strong title={resource.name}>
            <span className={styles.filenameStem}>{stem}</span>
            <span className={styles.filenameExt}>{extension}</span>
          </strong>
          <span>{formatBytes(resource.size)}</span>
          {error && (
            <span role="alert">{t("collaboration.resourceError")}</span>
          )}
        </div>
        <Button
          className={styles.download}
          size="small"
          type="text"
          loading={downloading}
          icon={<Download size={15} />}
          onClick={() => void download()}
          aria-label={t("chat.flow.downloadFile", { name: resource.name })}
          title={t("common.download")}
        />
      </article>
      {image && (
        <Image.PreviewGroup
          items={[image]}
          preview={{ visible: previewOpen, onVisibleChange: setPreviewOpen }}
        />
      )}
    </>
  );
}

/** Uses the root thread's authorized artifact list, including child expert results. */
export default function ChatDeliverables({
  agentId,
  threadId,
}: {
  agentId: string;
  threadId: string;
}) {
  const { t } = useTranslation();
  const { page, error, refresh } = useCollaboration(agentId, threadId);
  const [kind, setKind] = useState<DeliverableKind | "all">("all");
  const [limit, setLimit] = useState(DELIVERY_PAGE_SIZE);
  const [previewResource, setPreviewResource] =
    useState<CollaborationResource | null>(null);
  useEffect(() => {
    setKind("all");
    setLimit(DELIVERY_PAGE_SIZE);
    setPreviewResource(null);
  }, [agentId, threadId]);
  const resources = page.artifacts
    .filter(
      (resource) =>
        resource.source_kind !== "upload" &&
        resource.publication_state === "published",
    )
    .sort((a, b) => b.created_at - a.created_at);
  const counts = Object.fromEntries(
    DELIVERABLE_KINDS.map((type) => [
      type,
      resources.filter((resource) => deliverableKind(resource) === type).length,
    ]),
  );
  const filtered = resources.filter(
    (resource) => kind === "all" || deliverableKind(resource) === kind,
  );
  const visible = filtered.slice(0, limit);
  const many = resources.length > DELIVERY_PAGE_SIZE;
  const imageOverview =
    resources.length <= 4 &&
    resources.every((resource) => deliverableKind(resource) === "image");
  const filtering = kind !== "all";
  if (!resources.length && !error && !filtering) return null;
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
          aria-label={t("common.refresh")}
          title={t("common.refresh")}
        />
      </div>
      {(many || filtering) && (
        <div className={styles.filters}>
          <div
            className={styles.types}
            role="group"
            aria-label={t("chat.deliverables.fileType")}
          >
            {(["all", ...DELIVERABLE_KINDS] as const)
              .filter(
                (type) => type === "all" || counts[type] > 0 || type === kind,
              )
              .map((type) => (
                <button
                  key={type}
                  type="button"
                  aria-pressed={kind === type}
                  onClick={() => {
                    setKind(type);
                    setLimit(DELIVERY_PAGE_SIZE);
                  }}
                >
                  {t(`chat.deliverables.types.${type}`)}{" "}
                  <span>
                    {type === "all" ? resources.length : counts[type]}
                  </span>
                </button>
              ))}
          </div>
        </div>
      )}
      {error && <p role="status">{t("chat.deliverables.refreshFailed")}</p>}
      {filtered.length === 0 && (
        <p role="status">{t("chat.deliverables.noMatch")}</p>
      )}
      {visible.length > 0 && (
        <div
          className={`${styles.files} ${
            imageOverview ? styles.imageOverviewGrid : ""
          }`}
        >
          {visible.map((resource) => (
            <ResourceCard
              key={resource.resource_id + resource.version}
              agentId={agentId}
              threadId={threadId}
              resource={resource}
              onOpen={setPreviewResource}
              overview={imageOverview}
            />
          ))}
        </div>
      )}
      {many && (
        <div className={styles.pagination}>
          <span>
            {t("chat.deliverables.shown", {
              count: visible.length,
              total: filtered.length,
            })}
          </span>
          {visible.length < filtered.length && (
            <Button
              size="small"
              type="text"
              onClick={() => setLimit((value) => value + DELIVERY_PAGE_SIZE)}
            >
              {t("chat.deliverables.more", {
                count: Math.min(
                  DELIVERY_PAGE_SIZE,
                  filtered.length - visible.length,
                ),
              })}
            </Button>
          )}
          {limit > DELIVERY_PAGE_SIZE && (
            <Button
              size="small"
              type="text"
              onClick={() => setLimit(DELIVERY_PAGE_SIZE)}
            >
              {t("chat.deliverables.collapse")}
            </Button>
          )}
        </div>
      )}
      <Modal
        centered
        open={previewResource !== null}
        title={previewResource?.name}
        onCancel={() => setPreviewResource(null)}
        footer={null}
        width="min(920px, calc(100vw - 24px))"
        classNames={{ body: styles.previewBody }}
        destroyOnHidden
      >
        {previewResource && (
          <Suspense
            fallback={<p role="status">{t("collaboration.loading")}</p>}
          >
            <ResourcePanelContent
              key={previewResource.resource_id}
              agentId={agentId}
              threadId={threadId}
              resourceId={previewResource.resource_id}
            />
          </Suspense>
        )}
      </Modal>
    </section>
  );
}
