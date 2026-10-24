import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUnsavedChangesWarning } from "./useUnsavedChangesWarning";

function unloadingIsBlocked() {
  return !window.dispatchEvent(new Event("beforeunload", { cancelable: true }));
}

describe("unsaved form warning", () => {
  it("blocks reload only while edits or a save are pending", () => {
    const { rerender } = renderHook(useUnsavedChangesWarning, {
      initialProps: false,
    });
    expect(unloadingIsBlocked()).toBe(false);
    rerender(true);
    expect(unloadingIsBlocked()).toBe(true);
    rerender(false);
    expect(unloadingIsBlocked()).toBe(false);
  });
  it("removes the warning after leaving the editor", () => {
    const { unmount } = renderHook(() => useUnsavedChangesWarning(true));
    expect(unloadingIsBlocked()).toBe(true);
    unmount();
    expect(unloadingIsBlocked()).toBe(false);
  });
});
