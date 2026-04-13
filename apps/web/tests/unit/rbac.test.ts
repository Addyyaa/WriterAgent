import { describe, expect, it } from "vitest";

import { canAccess } from "@/modules/rbac/rules";

describe("RBAC rules", () => {
  it("admin should access owner scope", () => {
    expect(canAccess("admin", "owner")).toBe(true);
  });

  it("viewer should not access editor scope", () => {
    expect(canAccess("viewer", "editor")).toBe(false);
  });
});
