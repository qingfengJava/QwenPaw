import { describe, expect, it, beforeEach } from "vitest";
import {
  useAuthStore,
  selectIsAdmin,
  isAdminIdentity,
  AUTH_DISABLED_IDENTITY,
} from "./authStore";

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  it("starts anonymous and not loaded", () => {
    const s = useAuthStore.getState();
    expect(s.username).toBe("");
    expect(s.role).toBe("");
    expect(s.roles).toEqual([]);
    expect(s.loaded).toBe(false);
    expect(selectIsAdmin(s)).toBe(false);
  });

  it("setIdentity records the verify payload", () => {
    useAuthStore.getState().setIdentity({
      username: "bob",
      role: "employee",
      roles: ["employee", "team_lead"],
    });
    const s = useAuthStore.getState();
    expect(s.loaded).toBe(true);
    expect(s.username).toBe("bob");
    expect(selectIsAdmin(s)).toBe(false);
  });

  it("flat admin role counts as admin", () => {
    expect(
      isAdminIdentity({ username: "a", role: "admin", roles: [] }),
    ).toBe(true);
  });

  it("platform_admin RBAC role counts as admin", () => {
    expect(
      isAdminIdentity({
        username: "a",
        role: "employee",
        roles: ["platform_admin"],
      }),
    ).toBe(true);
  });

  it("team_lead alone is not admin", () => {
    expect(
      isAdminIdentity({ username: "a", role: "employee", roles: ["team_lead"] }),
    ).toBe(false);
  });

  it("auth-disabled identity keeps every menu visible", () => {
    expect(isAdminIdentity(AUTH_DISABLED_IDENTITY)).toBe(true);
  });

  it("clear resets to anonymous", () => {
    useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
    useAuthStore.getState().clear();
    const s = useAuthStore.getState();
    expect(s.loaded).toBe(false);
    expect(selectIsAdmin(s)).toBe(false);
  });
});
