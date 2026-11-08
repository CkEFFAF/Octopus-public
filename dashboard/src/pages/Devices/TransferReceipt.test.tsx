import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { devicesApi, type DeviceTransfer } from "../../api/modules/devices";
import TransferReceipt from "./TransferReceipt";
vi.mock("../../api/modules/devices", () => ({
  devicesApi: { transferStatus: vi.fn(), cancelTransfer: vi.fn() },
}));
const initial: DeviceTransfer = {
  transfer_id: "transfer",
  operation_id: "operation",
  status: "negotiating",
  preferred_transport: "auto",
  actual_transport: null,
  bytes_total: 100,
  bytes_done: 0,
  fallback_reason: null,
  failure_direction: null,
  error_code: null,
  audit_id: "audit-123",
  receipts: { source: false, target: false },
};
beforeEach(() => vi.resetAllMocks());
function receipt(value: DeviceTransfer) {
  vi.mocked(devicesApi.transferStatus).mockResolvedValue(value);
  return render(<TransferReceipt initial={value} />);
}
it("does not label a requested direct channel as an established P2P connection", () => {
  receipt({ ...initial, preferred_transport: "direct" });
  expect(screen.getByText("devices.p2p.unconfirmed")).toBeInTheDocument();
  expect(screen.queryByText("devices.p2p.direct")).not.toBeInTheDocument();
});
it("shows the actual cloud fallback and keeps unconfirmed receipts below completion", () => {
  receipt({
    ...initial,
    status: "pending_receipt",
    actual_transport: "hub",
    bytes_done: 100,
    fallback_reason: "TRANSFER_DIRECT_UNREACHABLE",
  });
  expect(screen.getByText("devices.p2p.hub")).toBeInTheDocument();
  expect(screen.getByText("pending_receipt")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "99",
  );
  expect(screen.getByText("audit-123")).toBeInTheDocument();
});
it("requires both receipts before displaying completion", () => {
  receipt({
    ...initial,
    status: "completed",
    actual_transport: "direct",
    bytes_done: 100,
    receipts: { source: true, target: false },
  });
  expect(screen.getByText("pending_receipt")).toBeInTheDocument();
  expect(
    screen.queryByText("devices.p2p.status.completed"),
  ).not.toBeInTheDocument();
});
