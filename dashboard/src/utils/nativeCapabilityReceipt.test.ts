import { expect, it } from "vitest";
import { nativeCapabilityStatus } from "./nativeCapabilityReceipt";

it("shows saved, tested, failed and deferred capability states without claiming activation", () => {
  const status = (name: string, value: unknown) =>
    nativeCapabilityStatus(name, JSON.stringify(value));
  expect(
    status("octop_connector_create", {
      saved: true,
      authentication_verified: false,
    }),
  ).toBe("capabilitySaved");
  expect(
    status("octop_mcp_upsert", {
      saved: true,
      effective: "saved_not_attached",
    }),
  ).toBe("capabilitySaved");
  expect(
    status("octop_connector_attach", {
      saved: true,
      current_conversation_update: { effective: "next_model_request" },
    }),
  ).toBe("capabilityNextRequest");
  expect(
    status("octop_plugin_install", {
      saved: true,
      effective: "after_current_turn",
    }),
  ).toBe("capabilityAfterTurn");
  expect(status("octop_connector_test", { ok: false, error: "denied" })).toBe(
    "capabilityFailed",
  );
  expect(status("octop_mcp_test", { ok: true })).toBe("capabilityTestPassed");
  expect(status("octop_skill_list", { skills: [] })).toBeNull();
  expect(status("unrelated", { saved: true })).toBeNull();
  expect(nativeCapabilityStatus("octop_skill_save", "broken")).toBeNull();
});
