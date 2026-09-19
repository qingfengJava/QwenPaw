/**
 * admin/permissions.ts — `/admin/permissions` client (M7 PG-RBAC permission management).
 */
import { request } from "../../request";

/** Permission record as returned by the backend. */
export interface PermissionRecord {
  id: string;
  code: string;
  name: string;
  resource: string;
  action: string;
  description: string;
  is_enabled: boolean;
  sort_order: number;
}

export interface PermissionCreateBody {
  code: string;
  name: string;
  resource?: string;
  action?: string;
  description?: string;
  is_enabled?: boolean;
  sort_order?: number;
}

export interface PermissionUpdateBody {
  code?: string;
  name?: string;
  resource?: string;
  action?: string;
  description?: string;
  is_enabled?: boolean;
  sort_order?: number;
}

export const adminPermissionsApi = {
  /** List permissions, optionally filtered by resource. */
  list: (resource?: string) => {
    const query = resource ? `?resource=${encodeURIComponent(resource)}` : "";
    return request<PermissionRecord[]>(`/admin/permissions${query}`);
  },

  /** Create a new permission entry. */
  create: (data: PermissionCreateBody) =>
    request<PermissionRecord>("/admin/permissions", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** Update an existing permission entry. */
  update: (id: string, data: PermissionUpdateBody) =>
    request<PermissionRecord>(`/admin/permissions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  /** Delete a permission entry. */
  delete: (id: string) =>
    request<void>(`/admin/permissions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  /** Get permission IDs assigned to a role. */
  getRolePermissions: (roleId: string) =>
    request<string[]>(`/admin/permissions/role/${encodeURIComponent(roleId)}`),

  /** Set (replace) permission IDs assigned to a role. */
  setRolePermissions: (roleId: string, permIds: string[]) =>
    request<void>(`/admin/permissions/role/${encodeURIComponent(roleId)}`, {
      method: "PUT",
      body: JSON.stringify({ permission_ids: permIds }),
    }),
};
