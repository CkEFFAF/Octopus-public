import { ExpertIcon } from "../../Experts/components/iconForName";
import styles from "../index.module.less";
import AnimatedExpertAvatar from "../../../components/AnimatedExpertAvatar";
import {
  resolveCharacter,
  type ExpertPhase,
} from "../../../components/AnimatedExpertAvatar/model";

export interface ChatAgentOption {
  agent_id: string;
  name: string;
  icon_name?: string | null;
  icon_url?: string | null;
  color?: string | null;
  is_shared?: boolean;
  is_owner?: boolean;
  owner_username?: string | null;
  /** Remote cloud-collab shadow expert. */
  bridge?: boolean;
  bridge_connection_id?: string | null;
  bridge_connection_name?: string | null;
  bridge_connection_icon?: string | null;
  bridge_disconnected?: boolean;
  bridge_inbound?: boolean;
}

interface ExpertAgentAvatarProps {
  iconName?: string | null;
  iconUrl?: string | null;
  color?: string | null;
  /** Lucide icon size inside the circle. */
  iconSize?: number;
  /** Avatar circle diameter in px. */
  size?: number;
  className?: string;
  /** Neutral styling for read-only history tags. */
  muted?: boolean;
  phase?: ExpertPhase;
  animated?: boolean;
}

export default function ExpertAgentAvatar({
  iconName,
  iconUrl,
  color,
  iconSize,
  size = 32,
  className,
  muted = false,
  phase = "idle",
  animated = true,
}: ExpertAgentAvatarProps) {
  const accent = muted ? "#94a3b8" : color || "#6366f1";
  const character = resolveCharacter(iconUrl);
  const photo = Boolean(iconUrl?.trim()) || !iconUrl;
  const inner = photo
    ? size
    : iconSize ?? Math.max(12, Math.round(size * 0.55));

  return (
    <span
      className={`${styles.expertAgentAvatar} ${className ?? ""}`}
      style={{
        width: size,
        height: size,
        color: accent,
        background: muted ? "rgba(148, 163, 184, 0.14)" : `${accent}1a`,
      }}
      data-working={
        animated &&
        !muted &&
        [
          "speaking",
          "thinking",
          "planning",
          "searching",
          "reading",
          "writing",
          "coding",
          "drawing",
          "analyzing",
          "running",
          "verifying",
          "collaborating",
          "handoff",
          "uploading",
          "downloading",
          "recovering",
        ].includes(phase)
      }
      aria-hidden
    >
      {character || !iconUrl ? (
        <AnimatedExpertAvatar
          species={character ?? "swallow"}
          phase={phase}
          animated={animated && !muted}
          size={size}
        />
      ) : (
        <ExpertIcon iconUrl={iconUrl} iconName={iconName} size={inner} />
      )}
    </span>
  );
}
