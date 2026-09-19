/**
 * admin/users.ts — `/admin/users` client (M4-6 backend, M5 frontend).
 */
import { request } from "../../request";
import type { AdminUserView, IdentityBindingView } from "./types";

export interface CreateUserBody {
  username: string;
  password: string;
  role?: string;
  display_name?: string;
  real_name?: string;
  phone?: string;
  gender?: number;
  position?: string;
  department_ids?: string[];
}

export interface UpdateUserBody {
  disabled?: boolean;
  role?: string;
  display_name?: string;
  real_name?: string;
  phone?: string;
  gender?: number;
  position?: string;
}

export interface ListUsersQuery {
  department_id?: string;
  disabled?: boolean;
  keyword?: string;
}

const enc = encodeURIComponent;

function toQuery(params: ListUsersQuery): string {
  const sp = new URLSearchParams();
  if (params.department_id) sp.set("department_id", params.department_id);
  if (params.disabled !== undefined && params.disabled !== null) {
    sp.set("disabled", String(params.disabled));
  }
  if (params.keyword && params.keyword.trim()) {
    sp.set("keyword", params.keyword.trim());
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const adminUsersApi = {
  list: (query: ListUsersQuery = {}) =>
    request<AdminUserView[]>(`/admin/users${toQuery(query)}`),

  create: (body: CreateUserBody) =>
    request<AdminUserView>("/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  update: (username: string, body: UpdateUserBody) =>
    request<AdminUserView>(`/admin/users/${enc(username)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  setPassword: (username: string, password: string) =>
    request<void>(`/admin/users/${enc(username)}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  grantRole: (username: string, role: string) =>
    request<void>(`/admin/users/${enc(username)}/roles`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),

  revokeRole: (username: string, role: string) =>
    request<void>(`/admin/users/${enc(username)}/roles/${enc(role)}`, {
      method: "DELETE",
    }),

  // ── Channel identity bindings ────────────────────────────

  listIdentityBindings: () =>
    request<IdentityBindingView[]>("/admin/users/identity-bindings"),

  createIdentityBinding: (body: IdentityBindingView) =>
    request<IdentityBindingView>("/admin/users/identity-bindings", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteIdentityBinding: (channel: string, externalUserId: string) =>
    request<void>(
      `/admin/users/identity-bindings/${enc(channel)}/${enc(externalUserId)}`,
      { method: "DELETE" },
    ),
};
