/**
 * adminMenu.test.ts — role-based filtering of the admin menu branch (M5).
 *
 * The `visible` callbacks read the auth store at render time; these tests
 * exercise the分流 decision matrix without rendering the Sidebar.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { BUILTIN_MENU } from "./builtinMenu";
import {
  useAuthStore,
  AUTH_DISABLED_IDENTITY,
} from "../../stores/authStore";

const ADMIN_PREFIX = "core.admin";

const adminItems = () =>
  BUILTIN_MENU.filter((item) => item.id.startsWith(ADMIN_PREFIX));

const employeeItems = () =>
  BUILTIN_MENU.filter((item) => !item.id.startsWith(ADMIN_PREFIX));

const isVisible = (item: (typeof BUILTIN_MENU)[number]): boolean =>
  item.visible?.() ?? true;

describe("admin menu role filtering (M5)", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  it("registers the full admin branch", () => {
    const ids = adminItems().map((item) => item.id);
    expect(ids).toContain("core.admin-group");
    expect(ids).toContain("core.admin-users");
    expect(ids).toContain("core.admin-roles");
    expect(ids).toContain("core.admin-teams");
    expect(ids).toContain("core.admin-agent-grants");
    expect(ids).toContain("core.admin-model-grants");
    expect(ids).toContain("core.admin-quotas");
    expect(ids).toContain("core.admin-audit");
    expect(ids).toContain("core.admin-knowledge");
  });

  it("hides the admin branch for anonymous identities", () => {
    for (const item of adminItems()) {
      expect(isVisible(item), item.id).toBe(false);
    }
  });

  it("hides the admin branch for employees", () => {
    useAuthStore.getState().setIdentity({
      username: "bob",
      role: "employee",
      roles: ["employee", "team_lead"],
    });
    for (const item of adminItems()) {
      expect(isVisible(item), item.id).toBe(false);
    }
  });

  it("shows the admin branch for the flat admin role", () => {
    useAuthStore.getState().setIdentity({
      username: "root",
      role: "admin",
      roles: [],
    });
    for (const item of adminItems()) {
      expect(isVisible(item), item.id).toBe(true);
    }
  });

  it("shows the admin branch for the platform_admin RBAC role", () => {
    useAuthStore.getState().setIdentity({
      username: "carol",
      role: "employee",
      roles: ["platform_admin"],
    });
    for (const item of adminItems()) {
      expect(isVisible(item), item.id).toBe(true);
    }
  });

  it("shows the admin branch when authentication is disabled", () => {
    useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
    for (const item of adminItems()) {
      expect(isVisible(item), item.id).toBe(true);
    }
  });

  it("keeps employee entries visible for every identity", () => {
    const identities = [
      { username: "", role: "", roles: [] },
      { username: "bob", role: "employee", roles: ["employee"] },
      { username: "root", role: "admin", roles: ["platform_admin"] },
    ];
    for (const identity of identities) {
      useAuthStore.getState().setIdentity(identity);
      for (const item of employeeItems()) {
        expect(isVisible(item), `${item.id} for ${identity.username}`).toBe(
          true,
        );
      }
    }
  });

  it("every admin entry routes to a registered admin route id", () => {
    const leaves = adminItems().filter((item) => !item.isGroup);
    for (const item of leaves) {
      expect(item.route, item.id).toBe(item.id);
    }
  });
});
