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
  owner_id?: string | null;
  visibility?: string;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  system_prompt?: string;
  /** "专家帮你做"任务模板（运营位）。 */
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  /** 使用案例（静态运营位）。 */
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
  /** 数字员工档案列（20260830 能力层）。 */
  department?: string;
  work_styles?: string[];
  work_modes?: string[];
  hire_date?: string | null;
  /** 技能绑定（详情端点填充；权威在 expert_skills 表）。 */
  skills?: Array<{ skill_name: string; enabled: boolean; seq?: number }>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ExpertCreateBody {
  name: string;
  icon?: string;
  description?: string;
  agent_spec?: Record<string, unknown>;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  system_prompt?: string;
  visibility?: string;
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
  department?: string;
  work_styles?: string[];
  work_modes?: string[];
  hire_date?: string | null;
}

export interface ExpertUpdateBody {
  name?: string;
  icon?: string;
  description?: string;
  agent_spec?: Record<string, unknown>;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  system_prompt?: string;
  visibility?: string;
  sample_tasks?: Array<{ title: string; prompt: string }> | null;
  showcase?: Array<{ title: string; desc: string; tags?: string[] }> | null;
  department?: string;
  work_styles?: string[];
  work_modes?: string[];
  hire_date?: string | null;
  hire_date_clear?: boolean;
}

/** 草稿调试实例启停结果（preview/start | preview/stop）。 */
export interface ExpertPreviewInstance {
  expert_id: string;
  agent_id: string;
  workspace_dir?: string;
  running: boolean;
}

/** 调试实例状态 + 草稿是否有未发布变更（工作台徽标数据源）。 */
export interface ExpertPreviewStatus {
  expert_id: string;
  agent_id: string;
  running: boolean;
  has_unpublished_changes: boolean;
  expert_status: ExpertRecord["status"];
  published_version: number | null;
  version: number;
}

/** 一条不可变发布快照（版本历史）。 */
export interface ExpertVersionInfo {
  version: number;
  published_by: string;
  published_at: string | null;
}

/** 版本恢复结果（快照 spec 写回草稿，需再次发布才影响线上）。 */
export interface ExpertVersionRestoreResult {
  expert_id: string;
  restored_version: number;
  agent_spec: Record<string, unknown>;
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

  // ── 草稿调试实例（与线上 expert_{id} 完全隔离，发布联动销毁）──

  previewStart: (expertId: string) =>
    request<ExpertPreviewInstance>(
      `/admin/experts/${enc(expertId)}/preview/start`,
      { method: "POST" },
    ),

  previewStop: (expertId: string) =>
    request<ExpertPreviewInstance>(
      `/admin/experts/${enc(expertId)}/preview/stop`,
      { method: "POST" },
    ),

  previewStatus: (expertId: string) =>
    request<ExpertPreviewStatus>(
      `/admin/experts/${enc(expertId)}/preview/status`,
    ),

  // ── 版本历史（published_experts 不可变快照链，只增）──

  listVersions: (expertId: string) =>
    request<{ versions: ExpertVersionInfo[] }>(
      `/admin/experts/${enc(expertId)}/versions`,
    ),

  restoreVersion: (expertId: string, version: number) =>
    request<ExpertVersionRestoreResult>(
      `/admin/experts/${enc(expertId)}/versions/${version}/restore`,
      { method: "POST" },
    ),
};
