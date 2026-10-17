/**
 * 0025.1 DEC-C13: Dashboard wire value for `mcp_servers`.
 *
 * - Cold start / untouched empty → `undefined` (omit key → BE full defaults).
 * - User cleared connectors, or ask/plan/team restricted → `[]` (true opt-out).
 * - Non-empty picks → that list (BE unions expert + device pack).
 */
export function resolveTurnMcpServersPayload(
  connectors: string[],
  opts: { restricted?: boolean; optedOut?: boolean } = {},
): string[] | undefined {
  if (opts.restricted) {
    return [];
  }
  const names = connectors.filter((n) => typeof n === "string" && n.trim());
  if (names.length > 0) {
    return names;
  }
  if (opts.optedOut) {
    return [];
  }
  return undefined;
}
