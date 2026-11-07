import { Image, Progress, Button } from "antd";
import { X, FileText, RotateCcw, UploadCloud } from "lucide-react";
import { useTranslation } from "react-i18next";
import { formatBytes } from "../../../utils/embeddingDownload";
import { useAuthImageSrc } from "../../../hooks/useAuthImageSrc";
import type { ChatAttachment } from "../hooks/useChat";
import type { AttachmentUpload } from "../hooks/useChatAttachments";
import type { KnowledgeBase } from "../../../api/modules/knowledgeBases";
import { ConnectorLogo } from "../../Agent/Connectors/connectorDefs";
import { knowledgeIconForName } from "../../KnowledgeBases/knowledgeIcons";
import { inferKindFromNameAndMime } from "../utils/chatAttachments";
import { ChatMediaPlayer } from "./ChatMediaPlayer";
import ContextChip from "./ContextChip";
import styles from "../index.module.less";

interface ChatInputPreviewBarProps {
  attachments: ChatAttachment[];
  uploading: boolean;
  uploads?: AttachmentUpload[];
  onCancelUpload?: (id: string) => void;
  onRetryUpload?: (id: string) => void;
  selectedConnectors: string[];
  selectedKnowledgeBaseIds: string[];
  availableConnectors?: {
    mcp_server_name: string;
    label: string;
    kind: string;
    default_open?: boolean;
  }[];
  availableKnowledgeBases?: KnowledgeBase[];
  onRemoveAttachment: (index: number) => void;
  onConnectorsChange?: (names: string[]) => void;
  onKnowledgeBaseIdsChange?: (ids: string[]) => void;
}

function ComposerImagePreview({
  url,
  alt,
  className,
}: {
  url: string;
  alt: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const { src, loadState } = useAuthImageSrc(url, alt);

  if (loadState === "loading") {
    return (
      <div
        aria-hidden
        className={className}
        style={{ background: "var(--fn-bg-secondary)" }}
      />
    );
  }

  if (loadState === "error" || !src) {
    return (
      <div
        className={className}
        role="img"
        aria-label={alt || t("chat.imageLoadFailed")}
        style={{
          background: "#fff1f0",
          color: "#cf1322",
          fontSize: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: 4,
        }}
      >
        {t("chat.imageLoadFailed")}
      </div>
    );
  }

  return (
    <Image
      src={src}
      alt={alt}
      width={64}
      height={64}
      style={{ objectFit: "cover", display: "block" }}
      preview={{ mask: false }}
    />
  );
}

export default function ChatInputPreviewBar({
  attachments,
  uploading,
  uploads = [],
  onCancelUpload,
  onRetryUpload,
  selectedConnectors,
  selectedKnowledgeBaseIds,
  availableConnectors,
  availableKnowledgeBases,
  onRemoveAttachment,
  onConnectorsChange,
  onKnowledgeBaseIdsChange,
}: ChatInputPreviewBarProps) {
  const { t } = useTranslation();
  const hasContent =
    attachments.length > 0 ||
    uploading ||
    uploads.length > 0 ||
    selectedConnectors.length > 0 ||
    selectedKnowledgeBaseIds.length > 0;

  if (!hasContent) return null;

  const imageAttachments = attachments.filter(
    (attachment) =>
      inferKindFromNameAndMime(
        attachment.mediaType,
        attachment.filename,
        attachment.kind,
      ) === "image",
  );

  return (
    <div className={styles.imagePreviewBar}>
      {imageAttachments.length > 0 ? (
        <Image.PreviewGroup>
          {attachments.map((attachment, idx) =>
            inferKindFromNameAndMime(
              attachment.mediaType,
              attachment.filename,
              attachment.kind,
            ) === "image" ? (
              <div
                key={`${attachment.url}-${idx}`}
                className={styles.imagePreviewItem}
              >
                <ComposerImagePreview
                  url={attachment.url}
                  alt={attachment.filename || "preview"}
                  className={styles.imagePreviewThumb}
                />
                <button
                  className={styles.imagePreviewRemove}
                  onClick={() => onRemoveAttachment(idx)}
                  aria-label={t("chat.flow.removeFile", {
                    name: attachment.filename || t("chat.flow.file"),
                  })}
                  type="button"
                >
                  <X size={12} />
                </button>
              </div>
            ) : null,
          )}
        </Image.PreviewGroup>
      ) : null}
      {attachments.map((attachment, idx) => {
        const kind = inferKindFromNameAndMime(
          attachment.mediaType,
          attachment.filename,
          attachment.kind,
        );
        if (kind === "image") return null;
        if (kind === "video" || kind === "audio") {
          return (
            <div
              key={`${attachment.url}-${idx}`}
              className={
                kind === "video"
                  ? styles.composerMediaItem
                  : styles.attachmentPreviewCard
              }
            >
              <ChatMediaPlayer
                url={attachment.url}
                filename={attachment.filename}
                workspacePath={attachment.workspacePath}
                mediaType={attachment.mediaType}
                kind={kind}
                compact
              />
              <button
                className={styles.imagePreviewRemove}
                onClick={() => onRemoveAttachment(idx)}
                aria-label={t("chat.flow.removeFile", {
                  name: attachment.filename || t("chat.flow.file"),
                })}
                type="button"
              >
                <X size={12} />
              </button>
            </div>
          );
        }
        return (
          <div
            key={`${attachment.url}-${idx}`}
            className={styles.attachmentPreviewCard}
          >
            <div className={styles.attachmentPreviewMeta}>
              <FileText size={14} className={styles.attachmentPreviewIcon} />
              <span className={styles.attachmentPreviewName}>
                {attachment.filename || attachment.url}
                <small
                  style={{
                    display: "block",
                    color: "var(--fn-text-secondary)",
                    fontWeight: 400,
                  }}
                >
                  {attachment.size !== undefined
                    ? `${formatBytes(attachment.size)} · `
                    : ""}
                  {t("chat.flow.fileReady")}
                </small>
              </span>
            </div>
            <button
              className={styles.imagePreviewRemove}
              onClick={() => onRemoveAttachment(idx)}
              aria-label={t("chat.flow.removeFile", {
                name: attachment.filename || t("chat.flow.file"),
              })}
              type="button"
            >
              <X size={12} />
            </button>
          </div>
        );
      })}
      {uploads.map((item) => (
        <div
          className={styles.uploadQueueItem}
          key={item.id}
          data-status={item.status}
        >
          <div className={styles.uploadQueueHeading}>
            <UploadCloud size={15} aria-hidden />
            <span className={styles.uploadQueueName} title={item.filename}>
              {item.filename}
            </span>
          </div>
          {item.status === "failed" ? (
            <span role="alert" className={styles.uploadQueueError}>
              {item.error}
            </span>
          ) : (
            <>
              <Progress
                percent={item.percent}
                size="small"
                status="normal"
                strokeColor="var(--fn-color-primary)"
              />
              <span role="status">
                {t(
                  item.percent === 100
                    ? "upload.registering"
                    : "upload.inProgress",
                )}
              </span>
            </>
          )}
          <div className={styles.uploadQueueActions}>
            {item.status === "failed" && (
              <Button
                size="small"
                icon={<RotateCcw size={12} />}
                onClick={() => onRetryUpload?.(item.id)}
              >
                {t("common.retry")}
              </Button>
            )}
            <Button
              type="text"
              size="small"
              onClick={() => onCancelUpload?.(item.id)}
            >
              {t(item.status === "failed" ? "upload.dismiss" : "common.cancel")}
            </Button>
          </div>
        </div>
      ))}
      {uploading && (
        <span role="status" className={styles.uploadPendingHint}>
          {t("chat.flow.uploadDoesNotBlock")}
        </span>
      )}
      {uploading && uploads.length === 0 && (
        <div className={styles.imagePreviewItem}>
          <div className={styles.imagePreviewLoading}>
            <div className={styles.uploadSpinner} />
          </div>
        </div>
      )}
      {availableConnectors &&
        onConnectorsChange &&
        selectedConnectors.map((name) => {
          const c = availableConnectors.find((x) => x.mcp_server_name === name);
          if (!c) return null;
          return (
            <ContextChip
              key={name}
              variant="connector"
              icon={<ConnectorLogo kind={c.kind} size={16} />}
              label={c.label}
              onRemove={() =>
                onConnectorsChange(selectedConnectors.filter((n) => n !== name))
              }
            />
          );
        })}
      {availableKnowledgeBases &&
        onKnowledgeBaseIdsChange &&
        selectedKnowledgeBaseIds.map((id) => {
          const knowledgeBase = availableKnowledgeBases.find(
            (base) => base.id === id,
          );
          if (!knowledgeBase) return null;
          return (
            <ContextChip
              key={id}
              variant="knowledge"
              icon={knowledgeIconForName(knowledgeBase.icon_name, 12)}
              label={knowledgeBase.name}
              onRemove={() =>
                onKnowledgeBaseIdsChange(
                  selectedKnowledgeBaseIds.filter((baseId) => baseId !== id),
                )
              }
            />
          );
        })}
    </div>
  );
}
