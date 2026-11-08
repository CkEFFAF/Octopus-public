import { describe, expect, it } from "vitest";
import { buildNavSections } from "../../layouts/sidebarNav";
import { canAccessKeys, pathPermissionKeys } from "../../utils/permissions";
import type { OctopUser } from "../../api/modules/auth";

describe("shared marketplace access", () => {
  const user = {
    id: 2,
    username: "alice",
    role: "user",
    permissions: [],
  } as unknown as OctopUser;
  it("allows every authenticated user to visit the marketplace", () => {
    const keys = pathPermissionKeys("/plugins");
    expect(keys).toBe("authenticated");
    expect(canAccessKeys(user, keys!)).toBe(true);
    expect(canAccessKeys(null, keys!)).toBe(false);
  });
  it("keeps server plugin management permission protected", () => {
    const keys = pathPermissionKeys("/admin/plugins");
    expect(canAccessKeys(user, keys!)).toBe(false);
  });
  it("exposes the marketplace in the normal user navigation", () => {
    const keys = buildNavSections(user).flatMap((section) =>
      section.items.map((item) => item.key),
    );
    expect(keys).toContain("plugin-market");
    expect(keys).not.toContain("admin-plugins");
  });
});
