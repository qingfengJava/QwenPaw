/**
 * admin/experts.ts — `/admin/experts` client (XianWork Phase 3).
 */
import { request } from "../../request";

export interface ExpertRecord {
  id: string;
  name: string;
  icon: string;
  description: string;
  agent_spec: Record<string, unknown>;
  status: "draft" | "published" | "archived";
  version: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExpertCreateBody {
  name: string;
  icon?: string;
  description?: string;
  agent_spec?: Record<string, unknown>;
}

export interface ExpertUpdateBody {
  name?: string;
  icon?: string;
  description?: string;
  agent_spec?: Record<string, unknown>;
}

const enc = encodeURIComponent;

export const adminExpertsApi = {
  list: (status?: string) =>
    request<ExpertRecord[]>(
      `/admin/experts${status ? `?status=${enc(status)}` : ""}`,
    ),

  get: (expertId: string) =>
    request<ExpertRecord>(`/admin/experts/${enc(expertId)}`),

  create: (body: ExpertCreateBody) =>
    request<ExpertRecord>("/admin/experts", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  update: (expertId: string, body: ExpertUpdateBody) =>
    request<ExpertRecord>(`/admin/experts/${enc(expertId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  remove: (expertId: string) =>
    request<void>(`/admin/experts/${enc(expertId)}`, { method: "DELETE" }),

  publish: (expertId: string) =>
    request<ExpertRecord>(`/admin/experts/${enc(expertId)}/publish`, {
      method: "POST",
    }),

  archive: (expertId: string) =>
    request<ExpertRecord>(`/admin/experts/${enc(expertId)}/archive`, {
      method: "POST",
    }),
};
