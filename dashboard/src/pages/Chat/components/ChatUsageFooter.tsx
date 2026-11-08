import { useTranslation } from "react-i18next";
import { Popover } from "antd";
import type { ChatMessage } from "../hooks/useChat";
import { formatTokenUsage, sumVisibleTurnUsage } from "../utils/chatUsage";
import styles from "./ChatUsageFooter.module.less";

export default function ChatUsageFooter({
  messages,
  hasMore,
  loading,
  unavailable = false,
}: {
  messages: ChatMessage[];
  hasMore: boolean;
  loading: boolean;
  unavailable?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const usage = sumVisibleTurnUsage(messages);
  if (loading)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.loading")}</span>
    );
  if (unavailable)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.unavailable")}</span>
    );
  if (!usage)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.noUsage")}</span>
    );
  const scope = t(
    hasMore ? "chatUsage.loadedMessages" : "chatUsage.sessionTotal",
  );
  const details = formatTokenUsage(usage, {
    input: t("chatUsage.input"),
    output: t("chatUsage.output"),
    total: t("chatUsage.total"),
    cacheHit: t("chatUsage.cacheHit"),
  });
  const total = new Intl.NumberFormat(i18n.language, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(usage.total_tokens ?? 0);
  const cache =
    usage.input_tokens && typeof usage.cache_read_tokens === "number"
      ? (usage.cache_read_tokens / usage.input_tokens) * 100
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
            {t("chatUsage.cacheHit")}{" "}
            {Number(cache.toFixed(cache > 0 && cache < 1 ? 2 : 1))}%
          </span>
        )}
      </button>
    </Popover>
  );
}
