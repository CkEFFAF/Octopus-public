import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  collaborationApi,
  downloadCollaborationResource,
  verifiedResourceContent,
  type CollaborationResource,
} from "../../../api/modules/collaboration";
import DocumentPreviewCore from "../../../components/DocumentPreviewCore";
import { getDocKind } from "../../../utils/docKind";
import styles from "./CollaborationPanel.module.less";

/** Immutable resource preview uses opaque identities, never workspace paths. */
export default function ResourcePanelContent({
  agentId,
  threadId,
  resourceId,
}: {
  agentId: string;
  threadId: string;
  resourceId: string;
}) {
  const { t } = useTranslation();
  const [resource, setResource] = useState<CollaborationResource | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setLoading(true);
    setError(false);
    setBlob(null);
    setUrl("");
    setText("");
    setResource(null);
    void (async () => {
      try {
        const metadata = await collaborationApi.resource(
          agentId,
          threadId,
          resourceId,
        );
        if (metadata.publication_state !== "published")
          throw new Error("resource_unavailable");
        const bytes = await verifiedResourceContent(
          agentId,
          threadId,
          metadata,
        );
        const content =
          metadata.media_type.startsWith("text/") ||
          /\.(md|json|csv|txt)$/i.test(metadata.name)
            ? await bytes.text()
            : "";
        if (!active) return;
        objectUrl = URL.createObjectURL(bytes);
        setResource(metadata);
        setBlob(bytes);
        setText(content);
        setUrl(objectUrl);
      } catch {
        if (active) setError(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [agentId, threadId, resourceId, revision]);
  const fetchBlob = useCallback(async () => {
    if (!blob) throw new Error("resource_unavailable");
    return blob;
  }, [blob]);
  const download = useCallback(async () => {
    if (!resource) return;
    try {
      await downloadCollaborationResource(agentId, threadId, resource);
    } catch {
      setError(true);
    }
  }, [agentId, threadId, resource]);
  const kind = resource ? getDocKind(resource.name) : null;
  return (
    <div className={styles.preview}>
      <div className={styles.row}>
        <button
          type="button"
          disabled={loading}
          onClick={() => setRevision((v) => v + 1)}
        >
          {t("common.refresh")}
        </button>
        <button
          type="button"
          disabled={!resource || loading || error}
          onClick={() => void download()}
        >
          {t("common.download")}
        </button>
      </div>
      {loading && <p role="status">{t("collaboration.loading")}</p>}
      {error && <p role="alert">{t("collaboration.resourceError")}</p>}
      {resource && !error && (
        <>
          <strong>{resource.name}</strong>
          <small>
            {t("collaboration.verified")}{" "}
            <code className={styles.version}>{resource.version}</code>
          </small>
          {kind ? (
            <DocumentPreviewCore
              kind={kind}
              filename={resource.name}
              fetchBlob={fetchBlob}
              onDownload={download}
            />
          ) : resource.media_type.startsWith("image/") ? (
            <img src={url} alt={resource.name} />
          ) : resource.media_type.startsWith("video/") ? (
            <video src={url} controls />
          ) : resource.media_type.startsWith("audio/") ? (
            <audio src={url} controls />
          ) : text ? (
            <pre className={styles.text}>{text}</pre>
          ) : (
            <p>{t("collaboration.noPreview")}</p>
          )}
        </>
      )}
    </div>
  );
}
