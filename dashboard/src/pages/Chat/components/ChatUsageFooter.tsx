import { useTranslation } from "react-i18next";
import { Popover } from "antd";
import type { ChatMessage } from "../hooks/useChat";
import {
  formatTokenUsage,
  reportedCacheRead,
  sumVisibleTurnUsage,
} from "../utils/chatUsage";
import { useRecentRequestUsage } from "../hooks/useRecentRequestUsage";
import styles from "./ChatUsageFooter.module.less";

export default function ChatUsageFooter({
  messages,
  hasMore,
  loading,
  unavailable = false,
  agentId,
  threadId,
  isStreaming = false,
}: {
  messages: ChatMessage[];
  hasMore: boolean;
  loading: boolean;
  unavailable?: boolean;
  agentId?: string;
  threadId?: string;
  isStreaming?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const usage = sumVisibleTurnUsage(messages);
  const recent = useRecentRequestUsage(agentId, threadId, isStreaming);
  const scoped = Boolean(agentId && threadId);
  if (loading)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.loading")}</span>
    );
  if (unavailable)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.unavailable")}</span>
    );
  if (!usage && !recent.entry?.actual_usage)
    return (
      <span data-testid="chat-usage-summary">
        {t(
          scoped && (recent.loading || (!recent.failed && isStreaming))
            ? "chatUsage.cachePending"
            : "chatUsage.noUsage",
        )}
      </span>
    );
  const scope = t(
    !usage
      ? "chatUsage.recentRequest"
      : hasMore
      ? "chatUsage.loadedMessages"
      : "chatUsage.sessionTotal",
  );
  const displayUsage = usage ?? recent.entry?.actual_usage;
  const details = formatTokenUsage(displayUsage ?? undefined, {
    input: t("chatUsage.input"),
    output: t("chatUsage.output"),
    total: t("chatUsage.total"),
    cacheHit: t("chatUsage.cacheHit"),
  });
  const total = new Intl.NumberFormat(i18n.language, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(displayUsage?.total_tokens ?? 0);
  const cacheUsage = scoped ? recent.entry?.actual_usage : usage;
  const cacheRead = reportedCacheRead(cacheUsage);
  const cache =
    cacheUsage?.input_tokens && cacheRead !== undefined
      ? (cacheRead / cacheUsage.input_tokens) * 100
      : null;
  return (
    <Popover
      trigger={["hover", "click"]}
      content={
        <div className={styles.details}>
          <strong>{scope}</strong>
          {details.map((part) => (
            <span key={part}>{part}</span>
          ))}
          {cache === null && <span>{t("chatUsage.cacheUnavailable")}</span>}
          {scoped && cache !== null && (
            <span>
              {t("chatUsage.recentCacheDetail", {
                input: cacheUsage?.input_tokens,
                cached: cacheRead,
              })}
            </span>
          )}
        </div>
      }
    >
      <button
        type="button"
        className={styles.summary}
        data-testid="chat-usage-summary"
        aria-label={t("chatUsage.details")}
      >
        {scope} {total}
        {cache !== null && (
          <span>
            {t(scoped ? "chatUsage.recentCacheHit" : "chatUsage.cacheHit")}{" "}
            {Number(cache.toFixed(cache > 0 && cache < 1 ? 2 : 1))}%
          </span>
        )}
        {scoped && cache === null && (
          <span>
            {t(
              recent.loading || (!recent.failed && isStreaming && !recent.entry)
                ? "chatUsage.cachePending"
                : "chatUsage.cacheUnavailable",
            )}
          </span>
        )}
      </button>
    </Popover>
  );
}
