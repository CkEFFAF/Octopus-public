import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  collaborationApi,
  downloadCollaborationResource,
  type CollaborationDetail,
  type CollaborationInvocation,
  type CollaborationResource,
  type CollaborationTarget,
} from "../../../api/modules/collaboration";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import { stripThinkingTags } from "../utils/chatAttachments";
import { useCollaboration } from "../hooks/useCollaboration";
import styles from "./CollaborationPanel.module.less";

const reasonKeys: Record<string, string> = {
  PEER_ACCEPTANCE_FAILED: "acceptanceFailed",
  PEER_ACCEPTANCE_INTERRUPTED: "acceptanceInterrupted",
  PEER_PREPARATION_FAILED: "preparationFailed",
  PEER_START_PERSISTENCE_FAILED: "startPersistenceFailed",
  PEER_CALL_FAILED: "callFailed",
  PEER_MODEL_FAILED: "modelFailed",
  PEER_RECEIPT_PERSISTENCE_FAILED: "receiptPersistenceFailed",
  PEER_CANCEL_REQUESTED: "cancelRequested",
  COLLABORATION_RESTART_UNCONFIRMED: "restartUnconfirmed",
  INVOCATION_CONFLICT: "invocationConflict",
  RESOURCE_SNAPSHOT_UNAVAILABLE: "snapshotUnavailable",
  RESOURCE_DELIVERY_FAILED: "deliveryFailed",
};

/** Never use a server error code or free-form message as visible text/key. */
function reasonKey(code: unknown): string {
  return typeof code === "string" &&
    Object.prototype.hasOwnProperty.call(reasonKeys, code)
    ? `collaboration.reasons.${reasonKeys[code]}`
    : "collaboration.reasons.unknown";
}

/** Only public text is rendered. Reasoning/tool/system blocks are never displayed. */
function publicText(content: unknown): string {
  if (typeof content === "string") return stripThinkingTags(content);
  if (!Array.isArray(content)) return "";
  return stripThinkingTags(
    content
      .filter(
        (block) => block?.type === "text" && typeof block.text === "string",
      )
      .map((block) => block.text)
      .join("\n"),
  );
}

function InvocationDetail({
  agentId,
  threadId,
  invocation,
}: {
  agentId: string;
  threadId: string;
  invocation: CollaborationInvocation;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [detail, setDetail] = useState<CollaborationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    collaborationApi
      .detail(agentId, threadId, invocation.invocation_id)
      .then((next) => {
        if (active) setDetail(next);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    agentId,
    threadId,
    invocation.invocation_id,
    invocation.updated_at,
    revision,
  ]);

  async function older() {
    if (loading || detail?.next_before == null) return;
    setLoading(true);
    try {
      const next = await collaborationApi.detail(
        agentId,
        threadId,
        invocation.invocation_id,
        detail.next_before,
      );
      setDetail((prev) => {
        const messages = new Map(
          [...(prev?.messages ?? []), ...next.messages].map((item) => [
            item.seq,
            item,
          ]),
        );
        return {
          ...next,
          messages: [...messages.values()].sort((a, b) => a.seq - b.seq),
        };
      });
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }
  return (
    <div className={styles.detail}>
      <strong>{t("collaboration.prompt")}</strong>
      <p className={styles.text}>{invocation.prompt}</p>
      {invocation.child_thread_id && (
        <Link
          to={`/chat/${encodeURIComponent(
            invocation.callee_agent_id,
          )}/${encodeURIComponent(invocation.child_thread_id)}`}
        >
          {t("collaboration.openChild")}
        </Link>
      )}
      <div className={styles.row}>
        <strong>{t("collaboration.messages")}</strong>
        <button
          type="button"
          disabled={loading}
          onClick={() => setRevision((v) => v + 1)}
        >
          {t("common.refresh")}
        </button>
      </div>
      {loading && <p role="status">{t("collaboration.loading")}</p>}
      {error && <p role="alert">{t("collaboration.detailError")}</p>}
      {detail?.has_more && (
        <button type="button" disabled={loading} onClick={() => void older()}>
          {t("collaboration.older")}
        </button>
      )}
      {detail &&
        !detail.messages.some(
          (item) =>
            ["user", "assistant"].includes(item.role) &&
            publicText(item.content),
        ) && <p>{t("collaboration.noMessages")}</p>}
      {detail?.messages
        .filter((item) => ["user", "assistant"].includes(item.role))
        .map((item) => {
          const text = publicText(item.content);
          return text ? (
            <div key={item.seq} className={styles.workingMessage}>
              <small>
                {t(`collaboration.role.${item.role}`)} ·{" "}
                {formatMessageTime(item.created_at * 1000, timezone)}
              </small>
              <p className={styles.text}>{text}</p>
            </div>
          ) : null;
        })}
    </div>
  );
}

export default function CollaborationPanel({
  agentId,
  threadId,
  agentNameById,
  onOpenResource,
}: {
  agentId: string;
  threadId: string;
  agentNameById?: Record<string, string>;
  onOpenResource: (resource: CollaborationResource) => void;
}) {
  const { t } = useTranslation();
  const { page, loading, error, refresh } = useCollaboration(agentId, threadId);
  const timezone = useServerTimezone();
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const name = (id: string) => agentNameById?.[id] || id;
  const targetLabel = (target: CollaborationTarget | null) =>
    !target
      ? t("collaboration.unresolved")
      : target.device_name ||
        target.device_id ||
        (target.target_kind === "local"
          ? t("devices.localExecution")
          : t("collaboration.unresolved"));
  const resources = page.artifacts.filter(
    (resource) =>
      resource.source_kind !== "upload" &&
      resource.publication_state !== "registered",
  );
  const detail = page.invocations.find(
    (item) => item.invocation_id === selected,
  );
  const latest = [...page.invocations].sort(
    (a, b) => b.created_at - a.created_at,
  )[0];
  async function download(resource: CollaborationResource) {
    setDownloading(resource.resource_id);
    setDownloadError(false);
    try {
      await downloadCollaborationResource(agentId, threadId, resource);
    } catch {
      setDownloadError(true);
    } finally {
      setDownloading(null);
    }
  }
  return (
    <section className={styles.panel} aria-label={t("collaboration.title")}>
      <div className={styles.row}>
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {t("collaboration.title")} · {page.invocations.length} ·{" "}
          {resources.length} {t("collaboration.artifacts")}
        </button>
        <button type="button" disabled={loading} onClick={() => void refresh()}>
          {t("common.refresh")}
        </button>
      </div>
      {!expanded && latest && (
        <p>
          {name(latest.callee_agent_id)} · {t("collaboration.device")}:{" "}
          {targetLabel(latest.resolved_target)} · {t("collaboration.transport")}
          : {t(`collaboration.status.${latest.transport_status}`)} ·{" "}
          {t("collaboration.outcome")}:{" "}
          {t(`collaboration.outcomeStatus.${latest.task_outcome}`)}
        </p>
      )}
      {loading && <small role="status">{t("collaboration.loading")}</small>}
      {error && <p role="alert">{t("collaboration.loadError")}</p>}
      {expanded && (
        <div className={styles.content}>
          {!loading &&
            !error &&
            !page.invocations.length &&
            !resources.length && <p>{t("collaboration.empty")}</p>}
          {page.invocations.map((item) => (
            <div key={item.invocation_id} className={styles.card}>
              <button
                type="button"
                className={styles.assignment}
                aria-expanded={selected === item.invocation_id}
                onClick={() =>
                  setSelected((prev) =>
                    prev === item.invocation_id ? null : item.invocation_id,
                  )
                }
              >
                <strong>{name(item.callee_agent_id)}</strong>
                <span>
                  {t("collaboration.device")}:{" "}
                  {targetLabel(item.resolved_target)}
                </span>
                <span>
                  {t("collaboration.transport")}:{" "}
                  {t(`collaboration.status.${item.transport_status}`)}
                </span>
                <span>
                  {t("collaboration.outcome")}:{" "}
                  {t(`collaboration.outcomeStatus.${item.task_outcome}`)}
                </span>
              </button>
              {item.error_code && (
                <p
                  role={
                    item.transport_status === "failed" ||
                    item.task_outcome === "failed"
                      ? "alert"
                      : "status"
                  }
                >
                  {t(reasonKey(item.error_code))}{" "}
                  {item.retryable && t("collaboration.retryable")}
                </p>
              )}
              {selected === item.invocation_id && (
                <>
                  <p>
                    {t("collaboration.requested")}:{" "}
                    {t(`collaboration.policy.${item.target_policy}`, {
                      defaultValue: t("collaboration.status.unknown"),
                    })}{" "}
                    {item.target_policy === "explicit"
                      ? ` · ${targetLabel(item.requested_target)}`
                      : ""}
                  </p>
                  {item.retry_of && (
                    <p>
                      {t("collaboration.retryOf")}: {item.retry_of}
                    </p>
                  )}
                  <InvocationDetail
                    key={item.invocation_id}
                    agentId={agentId}
                    threadId={threadId}
                    invocation={detail ?? item}
                  />
                  <strong>{t("collaboration.evidence")}</strong>
                  {page.events
                    .filter(
                      (event) => event.invocation_id === item.invocation_id,
                    )
                    .slice(-20)
                    .map((event) => (
                      <p key={event.event_id}>
                        {t(
                          `collaboration.events.${event.event_type.replace(
                            /\./g,
                            "_",
                          )}`,
                          { defaultValue: t("collaboration.eventUpdate") },
                        )}{" "}
                        · {formatMessageTime(event.created_at * 1000, timezone)}
                      </p>
                    ))}
                </>
              )}
            </div>
          ))}
          {resources.map((resource) => {
            const event = [...page.events]
              .reverse()
              .find(
                (item) =>
                  item.resource_id === resource.resource_id &&
                  [
                    "resource.delivered",
                    "resource.delivery_failed",
                    "resource.delivery_started",
                  ].includes(item.event_type),
              );
            const delivery =
              resource.delivery_status ??
              (event?.event_type === "resource.delivered"
                ? "completed"
                : event?.event_type === "resource.delivery_failed"
                ? "failed"
                : event?.event_type === "resource.delivery_started"
                ? "running"
                : null);
            const available = resource.publication_state === "published";
            const resourceError =
              "error_code" in resource ? resource.error_code : null;
            return (
              <div className={styles.card} key={resource.resource_id}>
                <strong>{resource.name}</strong>
                <p>
                  {name(resource.source_agent_id)} · {t("collaboration.device")}
                  :{" "}
                  {resource.source_device_id ||
                    (resource.source_kind === "device"
                      ? t("collaboration.unresolved")
                      : resource.source_kind === "local"
                      ? t("devices.localExecution")
                      : t("collaboration.expertStorage"))}
                </p>
                <p>
                  {t("collaboration.version")}:{" "}
                  <code className={styles.version}>{resource.version}</code> ·{" "}
                  {resource.size.toLocaleString()} B
                </p>
                {!available && (
                  <p role="status">{t("collaboration.resourceUnavailable")}</p>
                )}
                {(resourceError || !available) && (
                  <p role="status">{t(reasonKey(resourceError))}</p>
                )}
                {delivery && (
                  <p role={delivery === "failed" ? "alert" : "status"}>
                    {t(`collaboration.delivery.${delivery}`)}
                  </p>
                )}
                <div className={styles.row}>
                  <button
                    type="button"
                    disabled={!available}
                    onClick={() => onOpenResource(resource)}
                  >
                    {t("common.preview")}
                  </button>
                  <button
                    type="button"
                    disabled={!available || downloading !== null}
                    onClick={() => void download(resource)}
                  >
                    {t("common.download")}
                  </button>
                </div>
              </div>
            );
          })}
          {downloadError && (
            <p role="alert">{t("collaboration.resourceError")}</p>
          )}
          {page.has_more && (
            <button
              type="button"
              disabled={loading}
              onClick={() => void refresh()}
            >
              {t("collaboration.more")}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
