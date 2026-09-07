/**
 * adminMenu.test.ts — role-based filtering of the admin menu branch (M5).
 *
 * The `visible` callbacks read the auth store at render time; these tests
 * exercise the分流 decision matrix without rendering the Sidebar.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { BUILTIN_MENU } from "./builtinMenu";
import { routeRegistry } from "../../plugins/registry/store";
import "./builtinRoutes"; // 副作用导入：注册内置路由，供 routeRegistry 断言使用
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

  it("registers the full admin branch (strict set)", () => {
    const ids = adminItems()
      .map((item) => item.id)
      .sort();
    expect(ids).toEqual([
      "core.admin-agent-grants",
      "core.admin-audit",
      "core.admin-group",
      "core.admin-knowledge",
      "core.admin-model-grants",
      "core.admin-organization",
      "core.admin-pending",
      "core.admin-quotas",
      "core.admin-roles",
      "core.admin-teams",
      "core.admin-users",
    ]);
  });

  it("retired duplicate entries stay out of the admin branch", () => {
    const ids = adminItems().map((item) => item.id);
    // C1 去重：experts/expert-teams/workforce-runs 已并入 /agents 域，禁止复活
    expect(ids).not.toContain("core.admin-experts");
    expect(ids).not.toContain("core.admin-expert-teams");
    expect(ids).not.toContain("core.admin-workforce-runs");
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

  it("every menu leaf routes to a registered route id", () => {
    // 真断言：查 routeRegistry 而非自比 id，防「菜单指向已删路由」的静默死链。
    // 覆盖全菜单（不只 admin）。
    const routeIds = new Set(routeRegistry.snapshot().map((r) => r.id));
    const leaves = BUILTIN_MENU.filter((item) => !item.isGroup);
    for (const item of leaves) {
      expect(item.route, item.id).toBeDefined();
      expect(routeIds.has(item.route!), item.id).toBe(true);
    }
  });

  it("platform groups keep the accordion IA (staff/channels + capability)", () => {
    // 手风琴 IA：两个 platform 分组存在且标记为 group，叶子按域挂载。
    // 防复活断言：叶子被改回顶级平铺（parentId 丢失）时立刻报错。
    const byId = new Map(BUILTIN_MENU.map((item) => [item.id, item]));
    expect(byId.get("core.staff-channels-group")?.isGroup).toBe(true);
    expect(byId.get("core.capability-group")?.isGroup).toBe(true);
    expect(byId.get("core.agents")?.parentId).toBe(
      "core.staff-channels-group",
    );
    expect(byId.get("core.channels")?.parentId).toBe(
      "core.staff-channels-group",
    );
    expect(byId.get("core.inbox")?.parentId).toBe(
      "core.staff-channels-group",
    );
    expect(byId.get("core.models")?.parentId).toBe("core.capability-group");
    expect(byId.get("core.skill-pool")?.parentId).toBe(
      "core.capability-group",
    );
    expect(byId.get("core.marketplace")?.parentId).toBe(
      "core.capability-group",
    );
    // 工作台保持顶级直达（门户不折叠）。
    expect(byId.get("core.workbench")?.parentId).toBeUndefined();
  });
});
