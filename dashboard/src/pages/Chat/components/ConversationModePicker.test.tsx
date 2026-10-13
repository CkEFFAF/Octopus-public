import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConversationModePicker from "./ConversationModePicker";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("ConversationModePicker", () => {
  it("selects a mode from the menu", async () => {
    const onChange = vi.fn();
    render(
      <ConversationModePicker conversationMode="craft" onChange={onChange} />,
    );
    const trigger = screen.getByTestId("conversation-mode-picker");
    expect(trigger).not.toHaveTextContent("chat.workMode.agentic");
    fireEvent.click(trigger);
    const plan = await screen.findByText("chat.workMode.plan");
    expect(plan.closest("button")).toHaveTextContent("chat.workMode.planHint");
    fireEvent.click(plan);
    expect(onChange).toHaveBeenCalledWith("plan");
  });

  it("maps a workflow preset to the existing craft permission mode", async () => {
    const onChange = vi.fn();
    const onWorkModeChange = vi.fn();
    render(
      <ConversationModePicker
        conversationMode="craft"
        onChange={onChange}
        onWorkModeChange={onWorkModeChange}
      />,
    );
    fireEvent.click(screen.getByTestId("conversation-mode-picker"));
    fireEvent.click(await screen.findByText("chat.workMode.debug"));
    expect(onWorkModeChange).toHaveBeenCalledWith("debug");
    expect(onChange).toHaveBeenCalledWith("craft");
  });
});
