/**
 * admin/menus.ts — `/admin/menus` client (M7 PG-RBAC menu management).
 */
import { request } from "../../request";
import type { MenuItem } from "../../../stores/permissionStore";

export interface MenuCreateBody {
  parent_id?: string | null;
  name: string;
  menu_type: "directory" | "menu" | "button";
  path?: string;
  component?: string;
  icon?: string;
  perm_code?: string;
  sort_order?: number;
  is_visible?: boolean;
  is_enabled?: boolean;
  is_external?: boolean;
  redirect?: string;
}

export interface MenuUpdateBody {
  parent_id?: string | null;
  name?: string;
  menu_type?: "directory" | "menu" | "button";
  path?: string;
  component?: string;
  icon?: string;
  perm_code?: string;
  sort_order?: number;
  is_visible?: boolean;
  is_enabled?: boolean;
  is_external?: boolean;
  redirect?: string;
}

export const adminMenusApi = {
  /** Get the full menu tree. */
  getTree: () => request<MenuItem[]>("/admin/menus"),

  /** Get the flat menu list (no nesting). */
  getFlat: () => request<MenuItem[]>("/admin/menus/flat"),

  /** 强制重置菜单为内置 seed 结构（覆盖当前编辑）。 */
  reseed: () =>
    request<{ ok: boolean }>("/admin/menus/reseed", { method: "POST" }),

  /** Create a new menu entry. */
  create: (data: MenuCreateBody) =>
    request<MenuItem>("/admin/menus", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** Update an existing menu entry. */
  update: (id: string, data: MenuUpdateBody) =>
    request<MenuItem>(`/admin/menus/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  /** Delete a menu entry. */
  delete: (id: string) =>
    request<void>(`/admin/menus/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  /** Get menu IDs assigned to a role. */
  getRoleMenus: (roleId: string) =>
    request<string[]>(`/admin/menus/role/${encodeURIComponent(roleId)}`),

  /** Set (replace) menu IDs assigned to a role. */
  setRoleMenus: (roleId: string, menuIds: string[]) =>
    request<void>(`/admin/menus/role/${encodeURIComponent(roleId)}`, {
      method: "PUT",
      body: JSON.stringify({ menu_ids: menuIds }),
    }),
};
