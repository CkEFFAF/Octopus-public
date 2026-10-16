import {
  ICP_FILING_URL,
  resolveIcpFilingNumber,
} from "../../config/icpFiling";

type Props = {
  /** Override env/default (tests). */
  number?: string | null;
};

/**
 * Bottom-center ICP filing link for unauthenticated public shells.
 * Renders nothing when the filing number is empty/disabled.
 */
export default function IcpFilingFooter({ number }: Props) {
  const text =
    number === undefined ? resolveIcpFilingNumber() : number?.trim() || null;
  if (!text) return null;

  return (
    <footer
      data-testid="icp-filing-footer"
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: "max(12px, env(safe-area-inset-bottom, 0px))",
        zIndex: 1,
        textAlign: "center",
        pointerEvents: "none",
        padding: "0 12px",
      }}
    >
      <a
        href={ICP_FILING_URL}
        target="_blank"
        rel="noreferrer"
        data-testid="icp-filing-link"
        style={{
          pointerEvents: "auto",
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--fn-text-tertiary)",
          textDecoration: "none",
        }}
      >
        {text}
      </a>
    </footer>
  );
}
