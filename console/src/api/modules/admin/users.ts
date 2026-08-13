/**
 * admin/users.ts — `/admin/users` client (M4-6 backend, M5 frontend).
 */
import { request } from "../../request";
import type { AdminUserView } from "./types";

export interface CreateUserBody {
  username: string;
  password: string;
  role?: string;
  display_name?: string;
}

export interface UpdateUserBody {
  disabled?: boolean;
  role?: string;
  display_name?: string;
}

const enc = encodeURIComponent;

export const adminUsersApi = {
  list: () => request<AdminUserView[]>("/admin/users"),

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
};
