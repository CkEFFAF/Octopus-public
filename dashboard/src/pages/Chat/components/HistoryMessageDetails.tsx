import { useEffect, useRef, useState } from "react";
import { Alert, Button, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { extractContentBlocks } from "../../../utils/messageParser";
import type { ChatMessage } from "../hooks/sseHelpers";

interface HistoryMessageDetailsProps {
  detail: NonNullable<ChatMessage["historyDetail"]>;
}

export function HistoryMessageDetails({ detail }: HistoryMessageDetailsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<{ text: string; thinking: string } | null>(
    null,
  );
  const [failed, setFailed] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  useEffect(() => () => requestRef.current?.abort(), []);

  async function load() {
    requestRef.current?.abort();
    const request = new AbortController();
    requestRef.current = request;
    setFailed(false);
    setBody(null);
    try {
      const page = await octopThreadsApi.history(
        detail.agentId,
        detail.threadId,
        {
          limit: 1,
          cursor: detail.cursor,
          signal: request.signal,
        },
      );
      if (request.signal.aborted) return;
      const message = page.messages[0];
      if (
        page.thread_id !== detail.threadId ||
        page.history_loading ||
        page.detail_cursor !== detail.cursor ||
        message?.role !== "assistant"
      ) {
        setFailed(true);
        return;
      }
      const blocks = extractContentBlocks(message.content) ?? [];
      setBody({
        text: blocks
          .filter((block) => block.type === "text")
          .map((block) => block.content)
          .join(""),
        thinking: blocks
          .filter((block) => block.type === "thinking")
          .map((block) => block.content)
          .join("\n\n"),
      });
    } catch {
      if (!request.signal.aborted) setFailed(true);
    }
  }

  return (
    <>
      <Button
        type="link"
        size="small"
        onClick={() => {
          setOpen(true);
          void load();
        }}
      >
        {t("chat.historyFullMessage")}
      </Button>
      <Modal
        open={open}
        title={t("chat.historyFullMessage")}
        width={760}
        footer={null}
        loading={open && !body && !failed}
        destroyOnHidden
        onCancel={() => {
          requestRef.current?.abort();
          setOpen(false);
          setBody(null);
        }}
      >
        {failed && (
          <Alert
            type="error"
            message={t("chat.historyFullMessageFailed")}
            action={
              <Button size="small" onClick={() => void load()}>
                {t("common.retry")}
              </Button>
            }
          />
        )}
        {body?.text && (
          <Input.TextArea
            aria-label={t("chat.historyAnswerText")}
            readOnly
            rows={14}
            value={body.text}
          />
        )}
        {body?.thinking && (
          <details open={!body.text}>
            <summary>{t("chat.historyReasoningText")}</summary>
            <Input.TextArea
              aria-label={t("chat.historyReasoningText")}
              readOnly
              rows={10}
              value={body.thinking}
            />
          </details>
        )}
      </Modal>
    </>
  );
}
