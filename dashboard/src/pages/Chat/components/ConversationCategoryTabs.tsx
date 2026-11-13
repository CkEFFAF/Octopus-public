import { Segmented } from "antd";
import { useTranslation } from "react-i18next";
import type { ConversationCategory } from "../../../api/types/conversation";

export interface ConversationCategoryProps {
  category?: ConversationCategory;
  onCategoryChange?: (category: ConversationCategory) => void;
}

export default function ConversationCategoryTabs({
  category = "user",
  onCategoryChange,
}: ConversationCategoryProps) {
  const { t } = useTranslation();
  return (
    <div style={{ padding: "8px 10px" }}>
      <Segmented
        block
        aria-label={t("collaboration.conversationCategory")}
        value={category}
        onChange={(value) => onCategoryChange?.(value as ConversationCategory)}
        options={[
          { value: "user", label: t("collaboration.userConversations") },
          {
            value: "agent_collaboration",
            label: t("collaboration.agentConversations"),
          },
        ]}
      />
    </div>
  );
}
