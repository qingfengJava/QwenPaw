/**
 * admin/expertTeams.ts — `/admin/expert-teams` client (XianWork Phase 3).
 */
import { request } from "../../request";
import type { ExpertRecord } from "./experts";

export interface TeamMember {
  expert_id: string;
  role_hint: string;
  seq: number;
}

export interface ExpertTeamRecord {
  id: string;
  name: string;
  description: string;
  mode: "router" | "pipeline";
  router_prompt: string;
  status: "draft" | "published" | "archived";
  version: number;
  /** Workforce runtime orchestration spec (nodes/fast_nodes/policy/
   *  plan_note/runtime_enabled) — preset DAG template read by the planner. */
  orchestration?: Record<string, unknown> | null;
  /** "任务示例"模板（运营位；点击即以 prompt 为 goal 创建 run）。 */
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  /** 使用案例（静态运营位；与真实交付投影并存）。 */
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
  members: TeamMember[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TeamMemberBody {
  expert_id: string;
  role_hint?: string;
  seq?: number;
}

export interface ExpertTeamCreateBody {
  name: string;
  description?: string;
  mode?: string;
  router_prompt?: string;
  members?: TeamMemberBody[];
  orchestration?: Record<string, unknown> | null;
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
}

export interface ExpertTeamUpdateBody {
  name?: string;
  description?: string;
  mode?: string;
  router_prompt?: string;
  members?: TeamMemberBody[];
  orchestration?: Record<string, unknown> | null;
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
}

const enc = encodeURIComponent;

export const adminExpertTeamsApi = {
  list: (status?: string) =>
    request<ExpertTeamRecord[]>(
      `/admin/expert-teams${status ? `?status=${enc(status)}` : ""}`,
    ),

  get: (teamId: string) =>
    request<ExpertTeamRecord>(`/admin/expert-teams/${enc(teamId)}`),

  create: (body: ExpertTeamCreateBody) =>
    request<ExpertTeamRecord>("/admin/expert-teams", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  update: (teamId: string, body: ExpertTeamUpdateBody) =>
    request<ExpertTeamRecord>(`/admin/expert-teams/${enc(teamId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  remove: (teamId: string) =>
    request<void>(`/admin/expert-teams/${enc(teamId)}`, { method: "DELETE" }),

  publish: (teamId: string) =>
    request<ExpertTeamRecord>(`/admin/expert-teams/${enc(teamId)}/publish`, {
      method: "POST",
    }),

  archive: (teamId: string) =>
    request<ExpertTeamRecord>(`/admin/expert-teams/${enc(teamId)}/archive`, {
      method: "POST",
    }),
};

export type { ExpertRecord };
