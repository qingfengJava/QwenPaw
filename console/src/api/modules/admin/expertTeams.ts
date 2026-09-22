/**
 * admin/expertTeams.ts — `/admin/expert-teams` client (XianWork Phase 3).
 */
import { request } from "../../request";
import type { ExpertRecord } from "./experts";

export interface TeamMember {
  expert_id: string;
  role_hint: string;
  /** 团队内职责角色：lead=主理人 / member=成员（缺省 member）。 */
  member_role: string;
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
  /** 团队内职责角色（lead/member）；省略时后端补 member。 */
  member_role?: string;
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

/** GET /metadata — 团队配置元数据（角色/模式/默认限额；前端枚举唯一来源）。 */
export interface TeamMetadata {
  member_roles: Array<{ value: string; label: string }>;
  team_modes: Array<{ value: string; label: string }>;
  limits: {
    default_max_repair_per_node: number;
    default_max_replan: number;
    default_parallelism: number;
    default_max_total_seconds: number;
    default_max_total_tokens: number;
  };
}

/** GET /{team_id}/capabilities — 团队有效能力投影（声明≠可执行）。 */
export interface TeamCapabilityMember {
  expert_id: string;
  name: string;
  title: string;
  member_role: string;
  role_hint: string;
  /** 员工是否已发布（可执行前提；未发布即团队不可运行该成员）。 */
  published: boolean;
  skills: unknown[];
  tools: string[];
  kb_ids: string[];
  sops: unknown[];
  unavailable_reason: string;
}

export interface TeamCapabilityView {
  team_id: string;
  members: TeamCapabilityMember[];
}

/** GET /{team_id}/versions — 发布版本审计摘要（version 降序）。 */
export interface TeamVersionRow {
  team_id: string;
  version: number;
  published_by: string;
  published_at: string | null;
}

/** POST /{team_id}/validate — 发布预检结果（ok=false 时 issues 非空）。 */
export interface TeamValidateResult {
  ok: boolean;
  issues: string[];
  config: Record<string, unknown>;
  members: TeamCapabilityMember[];
}

const enc = encodeURIComponent;

/** 一条专家组↔知识库绑定行（T6；principal_type 恒为 team）。 */
export interface TeamKbBindingRow {
  agent_id: string;
  space_id: string;
  principal_type: string;
  space_name: string;
  scope: string;
  granted_by: string;
  remark: string;
  created_at: string;
}

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

  /** GET /metadata — 配置元数据（角色/模式/默认限额；枚举唯一来源）。 */
  metadata: () => request<TeamMetadata>("/admin/expert-teams/metadata"),

  /** GET /{team_id}/capabilities — 有效能力投影（能力矩阵数据源）。 */
  capabilities: (teamId: string) =>
    request<TeamCapabilityView>(
      `/admin/expert-teams/${enc(teamId)}/capabilities`,
    ),

  /** POST /{team_id}/validate — 发布预检（配置+成员可用性问题清单）。 */
  validate: (teamId: string) =>
    request<TeamValidateResult>(
      `/admin/expert-teams/${enc(teamId)}/validate`,
      { method: "POST" },
    ),

  /** GET /{team_id}/versions — 发布版本审计摘要（version 降序）。 */
  versions: (teamId: string) =>
    request<TeamVersionRow[]>(`/admin/expert-teams/${enc(teamId)}/versions`),

  /** GET /{team_id}/kb-bindings — 团队绑定行（名称/scope 已组装，T6）。 */
  listKbBindings: (teamId: string) =>
    request<TeamKbBindingRow[]>(
      `/admin/expert-teams/${enc(teamId)}/kb-bindings`,
    ),

  /** PUT /{team_id}/kb-bindings — 绑定一个库到团队（201/200 幂等）。 */
  bindKb: (teamId: string, spaceId: string, remark = "") =>
    request<TeamKbBindingRow & { created: boolean }>(
      `/admin/expert-teams/${enc(teamId)}/kb-bindings`,
      {
        method: "PUT",
        body: JSON.stringify({ space_id: spaceId, remark }),
      },
    ),

  /** DELETE /{team_id}/kb-bindings/{spaceId} (204)。 */
  unbindKb: (teamId: string, spaceId: string) =>
    request<void>(
      `/admin/expert-teams/${enc(teamId)}/kb-bindings/${enc(spaceId)}`,
      { method: "DELETE" },
    ),
};

export type { ExpertRecord };
