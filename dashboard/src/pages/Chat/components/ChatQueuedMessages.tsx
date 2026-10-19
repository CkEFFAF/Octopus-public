import { useRef, useState } from "react";
import { CornerDownRight, Loader2, Paperclip, Undo2 } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { QueuedChatItem } from "../hooks/useChatMessageQueue";
import styles from "../index.module.less";

interface ChatQueuedMessagesProps {
  items: QueuedChatItem[];
  onReclaim: (id: string) => void;
  onSteer?: (id: string) => boolean | Promise<boolean>;
  canSteer?: boolean;
  disabled?: boolean;
}

function previewText(item: QueuedChatItem): string {
  return item.text.trim().replace(/\s+/g, " ");
}

export default function ChatQueuedMessages({
  items,
  onReclaim,
  onSteer,
  canSteer = false,
  disabled = false,
}: ChatQueuedMessagesProps) {
  const { t } = useTranslation();
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const promotionPending = useRef(false);
  const promote = async (id: string) => {
    if (!onSteer || promotionPending.current) return;
    promotionPending.current = true;
    setPromotingId(id);
    try {
      await onSteer(id);
    } finally {
      promotionPending.current = false;
      setPromotingId(null);
    }
  };

  if (items.length === 0) return null;

  return (
    <div
      className={styles.queuedMessages}
      role="list"
      aria-label={t("chat.queue.label")}
    >
      {items.map((item, index) => {
        const text = previewText(item);
        const withdrawable =
          (!item.status || item.status === "queued") &&
          !promotingId &&
          !disabled;
        const attachmentCount = item.attachments?.length ?? 0;
        const label =
          text ||
          (attachmentCount > 0
            ? t("chat.queue.attachmentsOnly", {
                count: attachmentCount,
              })
            : t("chat.queue.emptyItem"));

        return (
          <div
            key={item.id}
            className={styles.queuedMessageItem}
            role="listitem"
          >
            <span className={styles.queuedMessageIndex}>{index + 1}</span>
            <button
              type="button"
              className={styles.queuedMessageBody}
              disabled={!withdrawable}
              onClick={() => onReclaim(item.id)}
              title={t("chat.queue.reclaim")}
            >
              <span className={styles.queuedMessageText}>{label}</span>
              {item.status && (
                <span role="status">
                  {t(`chat.queue.status.${item.status}`, {
                    defaultValue: item.status,
                  })}
                </span>
              )}
              {attachmentCount > 0 && text && (
                <span
                  className={styles.queuedMessageAttach}
                  title={t("chat.queue.attachmentCount", {
                    count: attachmentCount,
                  })}
                >
                  <Paperclip size={12} />
                  {attachmentCount}
                </span>
              )}
            </button>
            {onSteer && (
              <Tooltip
                title={
                  attachmentCount > 0
                    ? t("chat.steer.attachmentsQueue")
                    : item.text.trim().startsWith("/")
                    ? t("chat.steer.commandsQueue")
                    : t("chat.steer.action")
                }
              >
                <button
                  type="button"
                  className={styles.queuedMessageAction}
                  disabled={
                    !withdrawable ||
                    !canSteer ||
                    attachmentCount > 0 ||
                    !item.text.trim() ||
                    item.text.trim().startsWith("/")
                  }
                  onClick={() => void promote(item.id)}
                  aria-label={t("chat.steer.action")}
                >
                  {promotingId === item.id ? (
                    <Loader2 size={16} className={styles.spinIcon} />
                  ) : (
                    <CornerDownRight size={16} />
                  )}
                </button>
              </Tooltip>
            )}
            <Tooltip title={t("chat.queue.withdraw")}>
              <button
                type="button"
                className={styles.queuedMessageAction}
                disabled={!withdrawable}
                onClick={() => onReclaim(item.id)}
                aria-label={t("chat.queue.withdraw")}
                title={t("chat.queue.withdraw")}
              >
                <Undo2 size={16} />
              </button>
            </Tooltip>
          </div>
        );
      })}
    </div>
  );
}
