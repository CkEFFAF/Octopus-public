import { useTranslation } from "react-i18next";
import AnimatedExpertAvatar from "../../../components/AnimatedExpertAvatar";
import {
  resolveCharacter,
  type ExpertPhase,
} from "../../../components/AnimatedExpertAvatar/model";
import ExpertAgentAvatar from "./ExpertAgentAvatar";
import styles from "./ExpertActivity.module.less";

export default function ExpertActivity({
  phase,
  name,
  iconUrl,
  iconName,
  color,
  onConfigure,
}: {
  phase: ExpertPhase;
  name?: string;
  iconUrl?: string | null;
  iconName?: string | null;
  color?: string | null;
  onConfigure?: () => void;
}) {
  const { t } = useTranslation();
  const species = resolveCharacter(iconUrl);
  return (
    <button
      type="button"
      onClick={onConfigure}
      aria-label={t("chat.fileReview.configureExpert", { name })}
      className={styles.activity}
      data-phase={phase}
      title={`${name ?? ""} · ${t(`expertAnimation.phases.${phase}`)}`}
    >
      {species || !iconUrl ? (
        <AnimatedExpertAvatar
          species={species ?? "swallow"}
          phase={phase}
          size={40}
          interactive
        />
      ) : (
        <ExpertAgentAvatar
          iconUrl={iconUrl}
          iconName={iconName}
          color={color}
          size={40}
          interactive
        />
      )}
      <span className={styles.copy}>
        <strong>{name}</strong>
        <span>{t(`expertAnimation.phases.${phase}`)}</span>
      </span>
    </button>
  );
}
