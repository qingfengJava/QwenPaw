/**
 * admin/roles.ts — `/admin/roles` client (RBAC role CRUD).
 */
import { request } from "../../request";
import type { RoleRecord, RoleMemberView } from "./types";

export interface RoleBody {
  permissions: string[];
  description?: string;
  display_name?: string;
}

const enc = encodeURIComponent;

export const adminRolesApi = {
  list: () => request<RoleRecord[]>("/admin/roles"),

  listUsers: (name: string) =>
    request<RoleMemberView[]>(`/admin/roles/${enc(name)}/users`),

  upsert: (name: string, body: RoleBody) =>
    request<RoleRecord>(`/admin/roles/${enc(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  remove: (name: string) =>
    request<void>(`/admin/roles/${enc(name)}`, { method: "DELETE" }),
};
