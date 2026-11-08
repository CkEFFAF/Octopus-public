import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ExpertActivity from "./ExpertActivity";
it("opens expert configuration by clicking the single-chat header avatar", () => {
  const configure = vi.fn();
  render(
    <ExpertActivity
      name="GPU expert"
      phase="thinking"
      onConfigure={configure}
    />,
  );
  fireEvent.click(screen.getByRole("button"));
  expect(configure).toHaveBeenCalledOnce();
});
