import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FailureDiagnostics from "./FailureDiagnostics";

describe("model error details", () => {
  it("keeps technical diagnostics in a dialog until Details is clicked", async () => {
    render(
      <FailureDiagnostics
        summary="模型请求超时"
        value={{ code: "METADATA_TIMEOUT", request_id: "synthetic-request" }}
      />,
    );
    expect(screen.queryByText(/synthetic-request/)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "common.failureDetails" }),
    );
    expect(await screen.findByRole("dialog")).toHaveTextContent("模型请求超时");
    await waitFor(() =>
      expect(screen.getByText(/synthetic-request/)).toBeVisible(),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
