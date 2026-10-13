import AnimatedExpertAvatar from "../AnimatedExpertAvatar";
import styles from "./EmptyState.module.less";

interface OctopEmptyMascotProps {
  className?: string;
  /** Square edge in px; default 160. */
  size?: number;
}

/**
 * Octop empty-state mascot image with shared sizing.
 * Use inside custom empty UIs or pass as ``EmptyState`` icon /
 * antd ``Empty`` ``image``.
 */
export function OctopEmptyMascot({
  className,
  size = 160,
}: OctopEmptyMascotProps) {
  return (
    <AnimatedExpertAvatar
      species="swallow"
      phase="welcome"
      size={size}
      className={className ? `${styles.mascot} ${className}` : styles.mascot}
    />
  );
}
