import { useTranslation } from "react-i18next";
import { Pin, PinOff } from "lucide-react";
import type { OctopAgent } from "../../../context/AgentContext";
import {
  lifecyclePhase,
  type ExpertPhase,
} from "../../../components/AnimatedExpertAvatar/model";
import ExpertAgentAvatar from "./ExpertAgentAvatar";
import styles from "../index.module.less";

export function sidebarExpertPhase(
  agent: OctopAgent,
  activePhase?: ExpertPhase,
): ExpertPhase {
  const lifecycle = lifecyclePhase(agent.state, agent.bridge_disconnected);
  if (lifecycle !== "idle") return lifecycle;
  if (activePhase && activePhase !== "idle") return activePhase;
  return agent.is_working ? "running" : "idle";
}

export function ExpertStatusLabel({ phase }: { phase: ExpertPhase }) {
  const { t } = useTranslation();
  return (
    <span
      className={styles.expertStatusLabel}
      data-phase={phase}
      title={t(`expertAnimation.phases.${phase}`)}
    >
      <span className={styles.expertStatusDot} aria-hidden />
      <span className={styles.expertStatusText}>
        {t(`expertAnimation.phases.${phase}`)}
      </span>
    </span>
  );
}

export function ExpertPinButton({
  pinned,
  onClick,
}: {
  pinned: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={styles.expertPinButton}
      aria-pressed={pinned}
      aria-label={t(pinned ? "chat.unpinExpert" : "chat.pinExpert")}
      title={t(pinned ? "chat.unpinExpert" : "chat.pinExpert")}
      onKeyDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {pinned ? <PinOff size={14} /> : <Pin size={14} />}
    </button>
  );
}

export function PinnedExperts({
  agents,
  activeAgentId,
  activePhase,
  onSelect,
  onTogglePin,
}: {
  agents: OctopAgent[];
  activeAgentId: string | null;
  activePhase?: ExpertPhase;
  onSelect: (agentId: string) => void;
  onTogglePin: (agentId: string) => void;
}) {
  const { t } = useTranslation();
  if (!agents.length) return null;
  return (
    <section
      className={styles.pinnedExperts}
      aria-label={t("chat.pinnedExperts")}
    >
      <div className={styles.expertSectionTitle}>
        <Pin size={12} />
        {t("chat.pinnedExperts")}
      </div>
      <div className={styles.pinnedExpertGrid}>
        {agents.map((agent) => {
          const phase = sidebarExpertPhase(
            agent,
            agent.agent_id === activeAgentId ? activePhase : undefined,
          );
          return (
            <div
              key={agent.agent_id}
              className={`${styles.pinnedExpertCard} ${
                agent.agent_id === activeAgentId
                  ? styles.pinnedExpertActive
                  : ""
              }`}
            >
              <button
                type="button"
                className={styles.pinnedExpertSelect}
                onClick={() => onSelect(agent.agent_id)}
                aria-current={
                  agent.agent_id === activeAgentId ? "true" : undefined
                }
                title={agent.name}
              >
                <ExpertAgentAvatar
                  iconUrl={agent.icon_url}
                  iconName={agent.icon_name}
                  color={agent.color}
                  size={64}
                  phase={phase}
                />
                <span className={styles.pinnedExpertName}>{agent.name}</span>
                <ExpertStatusLabel phase={phase} />
                {!!agent.unread_count && (
                  <span
                    className={styles.pinnedExpertUnread}
                    aria-label={t("chat.unreadMessages")}
                  >
                    {agent.unread_count > 99 ? "99+" : agent.unread_count}
                  </span>
                )}
              </button>
              <ExpertPinButton
                pinned
                onClick={() => onTogglePin(agent.agent_id)}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}
