import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import atlas from "./atlas.json";
import {
  animationClip,
  characterUrl,
  type ExpertCharacter,
  type ExpertPhase,
} from "./model";
import styles from "./index.module.less";

export default function AnimatedExpertAvatar({
  species = "swallow",
  phase = "idle",
  size = 48,
  animated = true,
  className,
  portrait = false,
}: {
  species?: ExpertCharacter;
  phase?: ExpertPhase;
  size?: number;
  animated?: boolean;
  className?: string;
  portrait?: boolean;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId().replace(/:/g, "");
  const [visible, setVisible] = useState(true);
  const [foreground, setForeground] = useState(!document.hidden);
  const [reduced, setReduced] = useState(
    () =>
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false,
  );
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const [step, setStep] = useState({ key: "", index: 0 });
  const clip = useMemo(
    () => animationClip(portrait ? "idle" : phase, species),
    [portrait, phase, species],
  );
  const key = `${species}/${phase}/${portrait}`;
  const moving =
    animated &&
    visible &&
    foreground &&
    !reduced &&
    !portrait &&
    !["offline", "waiting_permission", "paused", "resting"].includes(phase);
  const index = moving && step.key === key ? step.index : 0;
  const frame = clip.frames[index] ?? clip.frames[0];
  const sheet = atlas[species];
  const crop = sheet.frames[frame];
  const url = characterUrl(species);
  useEffect(() => {
    const onVisibility = () => setForeground(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onMotion = () => setReduced(query?.matches ?? false);
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
  useEffect(() => {
    if (!moving || clip.frames.length < 2) return;
    const timeout = window.setTimeout(
      () => setStep({ key, index: (index + 1) % clip.frames.length }),
      clip.holds[index],
    );
    return () => clearTimeout(timeout);
  }, [key, index, moving, clip]);
  const label = `${t(`expertAnimation.characters.${species}`)} · ${t(
    `expertAnimation.phases.${phase}`,
  )}`;
  return (
    <span
      ref={ref}
      className={`${styles.avatar} ${className ?? ""}`}
      style={{ width: size, height: size }}
      data-species={species}
      data-phase={phase}
      data-frame={frame}
      data-animated={moving}
    >
      {failedUrl === url ? (
        <span className={styles.fallback} role="img" aria-label={label}>
          {t(`expertAnimation.characters.${species}`).slice(0, 1)}
        </span>
      ) : (
        <svg
          className={styles.body}
          viewBox={portrait ? sheet.portrait : "0 0 256 256"}
          role="img"
          aria-label={label}
        >
          <defs>
            <clipPath id={`${id}-crop`} clipPathUnits="userSpaceOnUse">
              <path d={crop.clip} />
            </clipPath>
          </defs>
          {visible && (
            <svg
              x={portrait ? 0 : 128 - (crop.w * sheet.scale) / 2}
              y={portrait ? 0 : 250 - crop.h * sheet.scale}
              width={portrait ? 256 : crop.w * sheet.scale}
              height={portrait ? 256 : crop.h * sheet.scale}
              viewBox={
                portrait
                  ? "0 0 256 256"
                  : `${crop.x} ${crop.y} ${crop.w} ${crop.h}`
              }
              overflow="hidden"
            >
              <image
                href={url}
                width="1536"
                height="1024"
                clipPath={`url(#${id}-crop)`}
                onError={() => setFailedUrl(url)}
              />
            </svg>
          )}
        </svg>
      )}
    </span>
  );
}
