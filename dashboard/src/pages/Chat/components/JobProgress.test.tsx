import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import JobProgress from "./JobProgress";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("renders only a script-reported percentage and updates without assuming completion", () => {
  const { rerender } = render(
    <JobProgress
      value={{
        source: "script_reported",
        percent: 35,
        phase: "核对文件",
        message: "70 / 200",
      }}
    />,
  );
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "35");
  expect(screen.getByText("核对文件")).toBeVisible();
  expect(screen.getByText("70 / 200")).toBeVisible();
  rerender(
    <JobProgress value={{ source: "script_reported", phase: "准备归档" }} />,
  );
  expect(screen.queryByRole("progressbar")).toBeNull();
  expect(screen.getByText("准备归档")).toBeVisible();
});

it("shows zero honestly and ignores estimates or malformed percentages", () => {
  const { rerender } = render(
    <JobProgress value={{ source: "elapsed_estimate", percent: 65 }} />,
  );
  expect(screen.queryByRole("progressbar")).toBeNull();
  rerender(<JobProgress value={{ source: "script_reported", percent: 0 }} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
  rerender(
    <JobProgress
      value={{ source: "script_reported", percent: 101, message: "检查中" }}
    />,
  );
  expect(screen.queryByRole("progressbar")).toBeNull();
  expect(screen.getByText("检查中")).toBeVisible();
});
