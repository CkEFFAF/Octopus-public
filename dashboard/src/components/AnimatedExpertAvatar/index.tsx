import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { animationUrl, type ExpertCharacter, type ExpertPhase } from "./model";
import styles from "./index.module.less";
import { observeProximity } from "./proximity";

export default function AnimatedExpertAvatar({
  species = "swallow",
  phase = "idle",
  size = 48,
  animated = true,
  className,
  portrait = false,
  interactive = false,
}: {
  species?: ExpertCharacter;
  phase?: ExpertPhase;
  size?: number;
  animated?: boolean;
  className?: string;
  portrait?: boolean;
  interactive?: boolean;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(true);
  const [foreground, setForeground] = useState(!document.hidden);
  const [reduced, setReduced] = useState(
    () =>
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false,
  );
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const [near, setNear] = useState(false);
  const reacting =
    interactive && near && visible && foreground && !reduced && !portrait;
  const displayedPhase = reacting && phase === "idle" ? "welcome" : phase;
  const moving =
    (animated || reacting) &&
    visible &&
    foreground &&
    !reduced &&
    !portrait &&
    !["offline", "paused", "resting"].includes(phase);
  const url = animationUrl(species, displayedPhase, moving);
  const still = animationUrl(species, phase, false);
  useEffect(() => {
    if (
      !interactive ||
      !visible ||
      !foreground ||
      reduced ||
      portrait ||
      !ref.current
    )
      return;
    return observeProximity(ref.current, setNear);
  }, [interactive, visible, foreground, reduced, portrait]);
  useEffect(() => {
    const onVisibility = () => setForeground(!document.hidden);
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onMotion = () => setReduced(query?.matches ?? false);
    document.addEventListener("visibilitychange", onVisibility);
    query?.addEventListener("change", onMotion);
    const observer =
      typeof IntersectionObserver !== "undefined"
        ? new IntersectionObserver(
            ([entry]) => setVisible(entry.isIntersecting),
            { rootMargin: "40px" },
          )
        : null;
    if (ref.current) observer?.observe(ref.current);
    return () => {
      observer?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      query?.removeEventListener("change", onMotion);
    };
  }, []);
  const label = `${t(`expertAnimation.characters.${species}`)} · ${t(
    `expertAnimation.phases.${phase}`,
  )}`;
  const source = failedUrl === url ? still : url;
  return (
    <span
      ref={ref}
      className={`${styles.avatar} ${className ?? ""}`}
      style={{ width: size, height: size }}
      data-species={species}
      data-phase={phase}
      data-animated={moving}
      data-expert-interactive={interactive || undefined}
      data-near={reacting || undefined}
    >
      {failedUrl === still ? (
        <span className={styles.fallback} role="img" aria-label={label}>
          {t(`expertAnimation.characters.${species}`).slice(0, 1)}
        </span>
      ) : (
        <img
          key={source}
          className={styles.body}
          src={source}
          width={size}
          height={size}
          alt={label}
          decoding="async"
          draggable={false}
          onError={() => setFailedUrl(source)}
        />
      )}
    </span>
  );
}
