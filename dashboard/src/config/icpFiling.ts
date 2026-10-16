/**
 * ICP filing number for the public dashboard shell.
 *
 * Build-time env: VITE_OCTOP_ICP_FILING_NUMBER (CI may map OCTOP_ICP_FILING_NUMBER).
 * Empty string hides the footer (self-hosted without filing).
 * When unset, this Octopus-public product defaults to the cloud filing number.
 */
export const ICP_FILING_URL = "https://beian.miit.gov.cn/";

/** Official filing for Octopus-public cloud; must include the -1 suffix. */
export const DEFAULT_ICP_FILING_NUMBER = "蜀ICP备2026062497号-1";

export function resolveIcpFilingNumber(
  raw: unknown = import.meta.env.VITE_OCTOP_ICP_FILING_NUMBER,
): string | null {
  if (raw === "") return null;
  if (typeof raw === "string" && raw.trim().length > 0) return raw.trim();
  return DEFAULT_ICP_FILING_NUMBER;
}
