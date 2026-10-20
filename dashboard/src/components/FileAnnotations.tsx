import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Checkbox, Empty, Input, Modal, Spin, Tag } from "antd";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  annotationsApi,
  type FileAnchor,
  type FileAnnotation,
  type ModificationRequest,
} from "../api/modules/annotations";
import type { CollaborationResource } from "../api/modules/collaboration";
import styles from "./FileAnnotations.module.less";

export default function FileAnnotations({
  agentId,
  threadId,
  resource,
  anchor,
  selectionRevision,
  onLocate,
  onResult,
  onClose,
}: {
  agentId: string;
  threadId: string;
  resource: CollaborationResource;
  anchor: FileAnchor;
  selectionRevision: number;
  onClose?: () => void;
  onLocate: (anchor: FileAnchor) => void;
  onResult: (resourceId: string) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<FileAnnotation[]>([]);
  const [requests, setRequests] = useState<ModificationRequest[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [reply, setReply] = useState<Record<string, string>>({});
  const [replying, setReplying] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(false);
  const [composing, setComposing] = useState(selectionRevision > 0);
  const [draftAnchor, setDraftAnchor] = useState(anchor);
  const lastSelection = useRef(selectionRevision);
  useEffect(() => {
    if (lastSelection.current === selectionRevision) return;
    lastSelection.current = selectionRevision;
    if (selectionRevision > 0) {
      setDraftAnchor(anchor);
      setComposing(true);
    }
  }, [anchor, selectionRevision]);
  const [next, setNext] = useState<number | null>(null);
  const command = useRef("");
  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [page, changes] = await Promise.all([
        annotationsApi.list(agentId, threadId, resource.resource_id),
        annotationsApi.requests(agentId, threadId, resource.resource_id),
      ]);
      setItems((old) =>
        old.length
          ? Array.from(
              new Map(
                [...old, ...page.items].map((item) => [
                  item.annotation_id,
                  item,
                ]),
              ).values(),
            )
          : page.items,
      );
      setNext((old) => old ?? (page.has_more ? page.next_cursor : null));
      setRequests(changes.items);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [agentId, threadId, resource.resource_id]);
  useEffect(() => {
    setSelected([]);
    void load();
  }, [load]);
  async function perform(task: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await task();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const chosen = items.filter((i) => selected.includes(i.annotation_id));
  async function sendReply(item: FileAnnotation) {
    const body = reply[item.annotation_id]?.trim();
    if (!body || busy) return;
    await perform(async () => {
      await annotationsApi.update(
        agentId,
        threadId,
        resource.resource_id,
        item.annotation_id,
        item.revision,
        { reply: body },
      );
      setReply((v) => ({ ...v, [item.annotation_id]: "" }));
      setReplying((current) =>
        current === item.annotation_id ? null : current,
      );
    });
  }
  return (
    <aside className={styles.panel} aria-label={t("workspace0034.annotations")}>
      <div className={styles.heading}>
        <strong>{t("workspace0034.annotations")}</strong>
        <span>
          <Button size="small" type="text" onClick={() => void load()}>
            {t("common.refresh")}
          </Button>
          {onClose && (
            <Button
              type="text"
              size="small"
              aria-label={t("common.close")}
              icon={<X size={16} />}
              onClick={onClose}
            />
          )}
        </span>
      </div>
      <small>
        {t("workspace0034.boundVersion")}{" "}
        <code>{resource.version.slice(0, 12)}</code>
      </small>
      {error && <Alert type="error" message={error} />}
      {!composing && (
        <Button
          onClick={() => {
            setDraftAnchor({ kind: "file" });
            setComposing(true);
          }}
        >
          {t("workspace0034.commentWholeFile")}
        </Button>
      )}
      {composing && (
        <>
          <Tag>
            {t(`workspace0034.anchor.${draftAnchor.kind}`)}
            {draftAnchor.page ? ` ${draftAnchor.page}` : ""}
            {draftAnchor.line ? ` L${draftAnchor.line}` : ""}
            {draftAnchor.start !== undefined
              ? ` ${draftAnchor.start.toFixed(1)}–${draftAnchor.end?.toFixed(
                  1,
                )}s`
              : ""}
          </Tag>
          {draftAnchor.quote && (
            <blockquote>{draftAnchor.quote.slice(0, 160)}</blockquote>
          )}
          <Input.TextArea
            value={text}
            maxLength={8000}
            rows={3}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("workspace0034.commentPlaceholder")}
          />
          <Button
            disabled={!text.trim() || busy}
            onClick={() =>
              void perform(async () => {
                await annotationsApi.create(
                  agentId,
                  threadId,
                  resource.resource_id,
                  resource.version,
                  draftAnchor,
                  text,
                );
                setText("");
                setComposing(false);
              })
            }
          >
            {t("workspace0034.saveComment")}
          </Button>
        </>
      )}
      {busy && <Spin size="small" />}
      {!busy && !items.length && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("workspace0034.noComments")}
        />
      )}
      {items.map((item) => (
        <article className={styles.comment} key={item.annotation_id}>
          <Checkbox
            checked={selected.includes(item.annotation_id)}
            onChange={(e) =>
              setSelected((current) =>
                e.target.checked
                  ? [...current, item.annotation_id]
                  : current.filter((id) => id !== item.annotation_id),
              )
            }
          >
            {t(`workspace0034.${item.status}`)}
          </Checkbox>
          <button
            className={styles.location}
            onClick={() => onLocate(item.anchor)}
          >
            {t(`workspace0034.anchor.${item.anchor.kind}`)}{" "}
            {item.anchor.page ??
              (item.anchor.line ? `L${item.anchor.line}` : "")}{" "}
            ↗
          </button>
          <p>{item.body}</p>
          {item.anchor.quote && (
            <blockquote>{item.anchor.quote.slice(0, 180)}</blockquote>
          )}
          {item.replies.map((r, i) => (
            <p key={i} className={styles.reply}>
              {r.body}
            </p>
          ))}
          {replying === item.annotation_id && (
            <Input
              autoFocus
              value={reply[item.annotation_id] ?? ""}
              onChange={(e) =>
                setReply((v) => ({
                  ...v,
                  [item.annotation_id]: e.target.value,
                }))
              }
              placeholder={t("workspace0034.reply")}
              onPressEnter={() => void sendReply(item)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setReplying(null);
              }}
            />
          )}
          <div className={styles.heading}>
            <Button
              size="small"
              type="text"
              disabled={
                busy ||
                (replying === item.annotation_id &&
                  !reply[item.annotation_id]?.trim())
              }
              onClick={() => {
                if (replying === item.annotation_id) void sendReply(item);
                else setReplying(item.annotation_id);
              }}
            >
              {t(
                replying === item.annotation_id
                  ? "workspace0034.sendReply"
                  : "workspace0034.reply",
              )}
            </Button>
            <Button
              size="small"
              type="text"
              disabled={busy}
              onClick={() =>
                void perform(() =>
                  annotationsApi.update(
                    agentId,
                    threadId,
                    resource.resource_id,
                    item.annotation_id,
                    item.revision,
                    { status: item.status === "open" ? "resolved" : "open" },
                  ),
                )
              }
            >
              {t(
                item.status === "open"
                  ? "workspace0034.resolve"
                  : "workspace0034.reopen",
              )}
            </Button>
          </div>
        </article>
      ))}
      {next !== null && (
        <Button
          onClick={() => {
            setBusy(true);
            void annotationsApi
              .list(agentId, threadId, resource.resource_id, next)
              .then((page) => {
                setItems((old) => [...old, ...page.items]);
                setNext(page.has_more ? page.next_cursor : null);
              })
              .catch((e) => setError(String(e)))
              .finally(() => setBusy(false));
          }}
        >
          {t("devices.native.more")}
        </Button>
      )}
      <Button
        type="primary"
        disabled={!chosen.length || busy}
        onClick={() => {
          command.current = crypto.randomUUID().replace(/-/g, "");
          setDraft(true);
        }}
      >
        {t("workspace0034.askAgent", { count: chosen.length })}
      </Button>
      {requests.map((request) => (
        <article key={request.request_id} className={styles.comment}>
          <Tag>{t(`workspace0034.requestState.${request.state}`)}</Tag>
          {request.receipt && (
            <small>
              {t("workspace0034.queueReceipt")}: {request.receipt.status}
            </small>
          )}
          {request.results.map((r) => (
            <Button key={r.resource_id} onClick={() => onResult(r.resource_id)}>
              {t("workspace0034.openResult")} {r.version.slice(0, 8)}
            </Button>
          ))}
        </article>
      ))}
      <Modal
        open={draft}
        title={t("workspace0034.modificationDraft")}
        onCancel={() => setDraft(false)}
        confirmLoading={busy}
        okText={t("workspace0034.submitQueue")}
        onOk={() =>
          void perform(async () => {
            await annotationsApi.submit(agentId, threadId, {
              command_id: command.current,
              resource_id: resource.resource_id,
              source_version: resource.version,
              annotations: chosen.map((i) => ({
                annotation_id: i.annotation_id,
                revision: i.revision,
              })),
            });
            setDraft(false);
          })
        }
      >
        <p>{t("workspace0034.queueHint")}</p>
        <p>{t("workspace0034.scopeCurrent")}</p>
        <p>
          {resource.name} · {resource.version.slice(0, 12)}
        </p>
        {chosen.map((i) => (
          <p key={i.annotation_id}>
            {t(`workspace0034.anchor.${i.anchor.kind}`)}: {i.body}
          </p>
        ))}
      </Modal>
    </aside>
  );
}
