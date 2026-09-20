/**
 * permissionStore.test.ts — auth-disabled menu tree fetch (2026-09-20 fix).
 *
 * loadAll() used to short-circuit entirely when auth was disabled, so the
 * backend menu tree stayed empty in single-user deployments. The fix keeps
 * the local ["*"] grant but still fetches /auth/menus — symmetric with the
 * backend, which now returns the full tree when auth is off. Failures must
 * degrade to [] (useDynamicMenus then falls back to the builtin menu).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/request", () => ({
  request: vi.fn(),
}));

import { request } from "../api/request";
import { AUTH_DISABLED_IDENTITY, useAuthStore } from "./authStore";
import { usePermissionStore, type MenuItem } from "./permissionStore";

const mockRequest = vi.mocked(request);

/** Build a MenuItem with test-friendly defaults. */
function menu(partial: Partial<MenuItem> & { id: string }): MenuItem {
  return {
    parent_id: null,
    name: partial.id,
    menu_type: "menu",
    path: "",
    component: "",
    icon: "",
    perm_code: "",
    sort_order: 0,
    is_visible: true,
    is_enabled: true,
    is_external: false,
    redirect: "",
    ...partial,
  };
}

const TREE: MenuItem[] = [
  menu({
    id: "m1",
    name: "系统",
    menu_type: "directory",
    children: [menu({ id: "m2", parent_id: "m1", name: "用户管理", path: "/admin/users" })],
  }),
];

function resetStores(): void {
  useAuthStore.setState({ username: "", role: "", roles: [], loaded: false });
  usePermissionStore.getState().reset();
}

describe("permissionStore.loadAll with auth disabled", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStores();
    useAuthStore.getState().setIdentity(AUTH_DISABLED_IDENTITY);
  });

  it("keeps the ['*'] grant and still fetches /auth/menus", async () => {
    mockRequest.mockResolvedValueOnce(TREE);

    await usePermissionStore.getState().loadAll();

    const s = usePermissionStore.getState();
    expect(s.permissions).toEqual(["*"]);
    expect(s.menus).toEqual(TREE);
    expect(s.loaded).toBe(true);
    expect(s.loading).toBe(false);
    expect(mockRequest).toHaveBeenCalledTimes(1);
    expect(mockRequest).toHaveBeenCalledWith("/auth/menus");
  });

  it("keeps menus [] and stays loaded when the menu fetch fails", async () => {
    mockRequest.mockRejectedValueOnce(new Error("Request failed: 503"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await usePermissionStore.getState().loadAll();

    const s = usePermissionStore.getState();
    expect(s.permissions).toEqual(["*"]);
    expect(s.menus).toEqual([]);
    expect(s.loaded).toBe(true);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("permissionStore.loadAll with auth enabled", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStores();
    useAuthStore.getState().setIdentity({
      username: "alice",
      role: "employee",
      roles: ["employee"],
    });
  });

  it("fetches permissions and menus in one pass", async () => {
    mockRequest.mockImplementation((path: string) =>
      Promise.resolve(
        path === "/auth/permissions" ? ["kb:read"] : [menu({ id: "m1" })],
      ),
    );

    await usePermissionStore.getState().loadAll();

    const s = usePermissionStore.getState();
    expect(s.permissions).toEqual(["kb:read"]);
    expect(s.menus).toEqual([menu({ id: "m1" })]);
    expect(s.loaded).toBe(true);
    expect(s.loading).toBe(false);
  });

  it("degrades gracefully when both fetches fail", async () => {
    mockRequest.mockRejectedValue(new Error("offline"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await usePermissionStore.getState().loadAll();

    const s = usePermissionStore.getState();
    expect(s.loaded).toBe(true);
    expect(s.loading).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});