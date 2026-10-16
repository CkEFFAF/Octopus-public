import { Dropdown } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useWelcomeQuickCardsLayout } from "../hooks/useWelcomeQuickCardsLayout";
import WelcomeQuickCards, { WelcomeQuickCardProbe } from "./WelcomeQuickCards";
import styles from "../index.module.less";
import AnimatedExpertAvatar from "../../../components/AnimatedExpertAvatar";
import {
  resolveCharacter,
  type ExpertPhase,
} from "../../../components/AnimatedExpertAvatar/model";
import { ExpertIcon } from "../../Experts/components/iconForName";

const welcomeActions: ExpertPhase[] = [
  "welcome",
  "reading",
  "coding",
  "success",
];

export interface WelcomeQuickCard {
  title: string;
  description: string;
  prompt: string;
  color: string;
  icon_name?: string | null;
  icon_url?: string | null;
  expertName?: string;
}

interface WelcomeScreenProps {
  onPromptClick: (text: string, options?: { prefill?: boolean }) => void;
  agentName?: string | null;
  iconUrl?: string | null;
  welcomeSuffix?: string | null;
  quickCards: WelcomeQuickCard[];
  hideMascot?: boolean;
  isTeam?: boolean;
  onConfigure?: () => void;
}

export default function WelcomeScreen({
  onPromptClick,
  agentName,
  iconUrl,
  welcomeSuffix,
  quickCards,
  hideMascot = false,
  isTeam = false,
  onConfigure,
}: WelcomeScreenProps) {
  const { t } = useTranslation();
  const [actionIndex, setActionIndex] = useState(0);
  const {
    welcomeRef,
    headingRef,
    sectionTitleRef,
    probeRef,
    expanded,
    setExpanded,
    cards,
    showToggle,
    autoHideMascot,
  } = useWelcomeQuickCardsLayout(quickCards);

  const handleMascotClick = () => {
    setActionIndex((prev) => (prev + 1) % welcomeActions.length);
  };

  const showMascot = !hideMascot && !autoHideMascot;

  return (
    <div className={styles.welcome} ref={welcomeRef}>
      <div className={styles.welcomeInner}>
        <div className={styles.welcomeHeading} ref={headingRef}>
          {showMascot && (
            <Dropdown
              disabled={!onConfigure}
              trigger={["click"]}
              menu={{
                items: [
                  {
                    key: "configure",
                    label: t("octopus.configuration"),
                    onClick: onConfigure,
                  },
                  {
                    key: "animate",
                    label: t("chatWelcome.mascotSwitchHint"),
                    onClick: handleMascotClick,
                  },
                ],
              }}
            >
              <button
                type="button"
                className={styles.welcomeMascot}
                onClick={onConfigure ? undefined : handleMascotClick}
                title={
                  onConfigure
                    ? t("octopus.configuration")
                    : t("chatWelcome.mascotSwitchHint")
                }
                aria-label={
                  onConfigure
                    ? t("octopus.configuration")
                    : t("expertAnimation.preview")
                }
              >
                {resolveCharacter(iconUrl) || !iconUrl ? (
                  <AnimatedExpertAvatar
                    species={resolveCharacter(iconUrl) ?? "swallow"}
                    phase={welcomeActions[actionIndex]}
                    size={132}
                  />
                ) : (
                  <ExpertIcon iconUrl={iconUrl} size={132} />
                )}
              </button>
            </Dropdown>
          )}
          <h1 className={styles.welcomeTitle}>
            {isTeam
              ? t("chatWelcome.teamHeading", {
                  name: agentName?.trim() || t("chatWelcome.teamNameFallback"),
                })
              : t("chatWelcome.greeting")}
          </h1>
          <p className={styles.welcomeSubtitle}>
            {isTeam ? (
              <span className={styles.welcomeSubtitleText}>
                {welcomeSuffix ?? t("chatWelcome.descriptionWithTeamSuffix")}
              </span>
            ) : agentName ? (
              <>
                <span className={styles.welcomeAgentLine}>
                  <span className={styles.welcomeAgentMention}>
                    @{agentName}
                  </span>
                </span>
                <span className={styles.welcomeSubtitleText}>
                  {welcomeSuffix ?? t("chatWelcome.descriptionWithAgentSuffix")}
                </span>
              </>
            ) : (
              t("chatWelcome.description")
            )}
          </p>
        </div>

        {quickCards.length > 0 && (
          <WelcomeQuickCards
            cards={cards}
            showToggle={showToggle}
            expanded={expanded}
            onToggle={() => setExpanded((prev) => !prev)}
            onPromptClick={onPromptClick}
            sectionTitleRef={sectionTitleRef}
          />
        )}
      </div>

      {quickCards.length > 0 && <WelcomeQuickCardProbe probeRef={probeRef} />}
    </div>
  );
}
