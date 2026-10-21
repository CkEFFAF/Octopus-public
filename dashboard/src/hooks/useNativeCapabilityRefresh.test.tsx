import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { emitToolEvent } from "../pages/Chat/hooks/chatStore";
import { useNativeCapabilityRefresh } from "./useNativeCapabilityRefresh";

it("refreshes scoped panels only after saved writes and includes global plugin installation", () => {
  const skills = vi.fn().mockResolvedValue(undefined);
  const tools = vi.fn().mockResolvedValue(undefined);
  const { unmount } = renderHook(() => {
    useNativeCapabilityRefresh("expertA", "skills", skills);
    useNativeCapabilityRefresh("expertA", "tools", tools);
  });
  const emit = (toolName: string, agentId: string, saved: boolean) =>
    act(() =>
      emitToolEvent({
        kind: "toolDone",
        sessionId: "thread",
        toolId: "native",
        toolName,
        result: JSON.stringify({ agent_id: agentId, saved }),
      }),
    );
  emit("octop_skill_save", "expertB", true);
  emit("octop_skill_save", "expertA", false);
  expect(skills).not.toHaveBeenCalled();
  emit("octop_skill_save", "expertA", true);
  expect(skills).toHaveBeenCalledTimes(1);
  expect(tools).not.toHaveBeenCalled();
  emit("octop_tool_set_enabled", "expertA", true);
  expect(tools).toHaveBeenCalledTimes(1);
  emit("octop_plugin_install", "expertB", true);
  expect(skills).toHaveBeenCalledTimes(2);
  expect(tools).toHaveBeenCalledTimes(2);
  unmount();
  emit("octop_skill_save", "expertA", true);
  expect(skills).toHaveBeenCalledTimes(2);
});
