import { Tag } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { ConversationOrigin } from "../../../api/types/conversation";

export default function ConversationSource({
  origin,
  agentId,
}: {
  origin: ConversationOrigin;
  agentId?: string | null;
}) {
  const { t } = useTranslation();
  if (origin.category !== "agent_collaboration") return null;
  const source = origin.collaboration_source;
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 8,
        padding: "6px 16px",
        fontSize: 12,
      }}
    >
      <Tag style={{ margin: 0 }}>
        {t(
          source?.runner_name
            ? "collaboration.acpConversation"
            : "collaboration.agentConversations",
        )}
      </Tag>
      {origin.actor?.name ? <span>{origin.actor.name}</span> : null}
      {source?.runner_name ? <span>{source.runner_name}</span> : null}
      {source?.device_id ? (
        <span>
          {t("collaboration.sourceDevice", { name: source.device_id })}
        </span>
      ) : null}
      {source?.parent_thread_id && agentId ? (
        <Link
          to={`/chat/${encodeURIComponent(agentId)}/${encodeURIComponent(
            source.parent_thread_id,
          )}`}
        >
          {t("collaboration.parentConversation")}
        </Link>
      ) : null}
    </div>
  );
}
