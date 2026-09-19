/**
 * admin/dataScopes.ts — `/admin/data-scopes` client (M7 PG-RBAC data scope management).
 */
import { request } from "../../request";

/** Data scope record as returned by the backend. */
export interface DataScopeRecord {
  id: string;
  role_id: string;
  resource: string;
  scope_type: "all" | "own" | "team" | "custom";
  scope_value: string;
  description: string;
}

export interface DataScopeBody {
  resource: string;
  scope_type: "all" | "own" | "team" | "custom";
  scope_value?: string;
  description?: string;
}

export const adminDataScopesApi = {
  /** Get all data scopes for a role. */
  getRoleScopes: (roleId: string) =>
    request<DataScopeRecord[]>(
      `/admin/data-scopes/role/${encodeURIComponent(roleId)}`,
    ),

  /** Set (create or update) a data scope for a role. */
  setRoleScope: (roleId: string, data: DataScopeBody) =>
    request<DataScopeRecord>(
      `/admin/data-scopes/role/${encodeURIComponent(roleId)}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
      },
    ),

  /** Delete a specific resource scope from a role. */
  deleteRoleScope: (roleId: string, resource: string) =>
    request<void>(
      `/admin/data-scopes/role/${encodeURIComponent(roleId)}/${encodeURIComponent(resource)}`,
      { method: "DELETE" },
    ),
};
