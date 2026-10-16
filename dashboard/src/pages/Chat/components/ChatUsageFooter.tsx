import { useTranslation } from "react-i18next";
import type { ChatMessage } from "../hooks/useChat";
import { formatTokenUsage, sumVisibleTurnUsage } from "../utils/chatUsage";

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
  const { t } = useTranslation();
  const usage = sumVisibleTurnUsage(messages);
  if (loading)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.loading")}</span>
    );
  if (unavailable)
    return (
      <span data-testid="chat-usage-summary">{t("chatUsage.unavailable")}</span>
    );
  return (
    <span data-testid="chat-usage-summary">
      {t(hasMore ? "chatUsage.loadedMessages" : "chatUsage.sessionTotal")}:{" "}
      {usage
        ? formatTokenUsage(usage, {
            input: t("chatUsage.input"),
            output: t("chatUsage.output"),
            total: t("chatUsage.total"),
            cacheHit: t("chatUsage.cacheHit"),
          }).join(" / ")
        : t("chatUsage.noUsage")}
    </span>
  );
}
