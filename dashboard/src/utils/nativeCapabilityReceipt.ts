/** Distinguish saving configuration from enabling capabilities or verifying a login. */
export function nativeCapabilityStatus(
  toolName: string,
  output?: string,
): string | null {
  if (!/^octop_(connector|mcp|skill|tool|plugin)_/.test(toolName) || !output)
    return null;
  try {
    const value = JSON.parse(output) as Record<string, unknown> | null;
    if (!value || typeof value !== "object") return null;
    if (value.error || value.ok === false) return "capabilityFailed";
    if (value.ok === true) return "capabilityTestPassed";
    if (value.saved !== true) return null;
    if (value.effective === "after_current_turn") return "capabilityAfterTurn";
    const update = value.current_conversation_update as Record<
      string,
      unknown
    > | null;
    if (
      value.effective === "next_model_request" ||
      update?.effective === "next_model_request"
    )
      return "capabilityNextRequest";
    return "capabilitySaved";
  } catch {
    return null;
  }
}
