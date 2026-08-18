/**
 * admin/workforce.ts — `/admin/workforce` client: tenant-wide team-run
 * operations view (list / stats) and the orchestration test-run entry.
 */
import { request } from "../../request";

/** run 状态机值（与后端 contracts.RUN_STATUS_* 对齐）。 */
export type AdminRunStatus =
  | "planning"
  | "awaiting_confirm"
  | "running"
  | "verifying"
  | "repairing"
  | "aggregating"
  | "done"
  | "failed"
  | "escalated"
  | "canceled"
  | "interrupted";

export interface AdminTeamRun {
  id: string;
  team_id: string;
  project_id: string | null;
  source_chat_id: string | null;
  initiator_id: string;
  status: AdminRunStatus;
  goal: string;
  repair_count: number;
  replan_count: number;
  escalation_reason: string | null;
  error: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AdminRunStats {
  total_runs: number;
  done: number;
  failed: number;
  escalated: number;
  active: number;
  repaired_runs: number;
  repair_total: number;
  replan_total: number;
  tokens_total: number;
  repair_rate: number;
  escalation_rate: number;
}

const enc = encodeURIComponent;

export const adminWorkforceApi = {
  /** 全租户 run 列表（管理端只读视图）。 */
  listRuns: (params: { team_id?: string; status?: string; limit?: number } = {}) => {
    const usp = new URLSearchParams();
    if (params.team_id) usp.set("team_id", params.team_id);
    if (params.status) usp.set("status", params.status);
    if (params.limit) usp.set("limit", String(params.limit));
    const qs = usp.toString();
    return request<AdminTeamRun[]>(`/admin/workforce/runs${qs ? `?${qs}` : ""}`);
  },

  /** 运行统计聚合（状态分布 / 返工率 / 升级率 / token 成本）。 */
  stats: () => request<AdminRunStats>("/admin/workforce/stats"),

  /** 团队编排配置试运行（创建测试 run 并后台启动引擎）。 */
  testRun: (teamId: string, goal = "") =>
    request<AdminTeamRun>(`/admin/workforce/teams/${enc(teamId)}/test-run`, {
      method: "POST",
      body: JSON.stringify({ goal }),
    }),
};
