/**
 * admin/orgs.ts — `/admin/orgs` client (XianWork Phase 1).
 */
import { request } from "../../request";

export interface OrgRecord {
  id: string;
  name: string;
  slug: string;
  plan: string;
  status: string;
  settings: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DepartmentTree {
  id: string;
  parent_id: string | null;
  name: string;
  path: string;
  description: string;
  children: DepartmentTree[];
}

const enc = encodeURIComponent;

export const adminOrgsApi = {
  listOrgs: () => request<OrgRecord[]>("/admin/orgs"),

  createOrg: (body: { name: string; slug: string; plan?: string }) =>
    request<OrgRecord>("/admin/orgs", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  departmentTree: () => request<DepartmentTree[]>("/admin/orgs/departments"),

  createDepartment: (body: {
    name: string;
    parent_id?: string | null;
    description?: string;
  }) =>
    request<{ id: string; path: string }>("/admin/orgs/departments", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateDepartment: (
    deptId: string,
    body: { name?: string; description?: string },
  ) =>
    request<{ ok: boolean }>(`/admin/orgs/departments/${enc(deptId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteDepartment: (deptId: string) =>
    request<void>(`/admin/orgs/departments/${enc(deptId)}`, {
      method: "DELETE",
    }),

  departmentMembers: (deptId: string) =>
    request<{ department_id: string; members: string[] }>(
      `/admin/orgs/departments/${enc(deptId)}/members`,
    ),

  assignMember: (deptId: string, username: string) =>
    request<void>(`/admin/orgs/departments/${enc(deptId)}/members`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  removeMember: (deptId: string, username: string) =>
    request<void>(
      `/admin/orgs/departments/${enc(deptId)}/members/${enc(username)}`,
      { method: "DELETE" },
    ),
};
