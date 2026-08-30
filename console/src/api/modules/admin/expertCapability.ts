/**
 * admin/expertCapability.ts — 数字员工能力层客户端（20260830）。
 *
 * 对应后端 `routers/admin/expert_capability.py`：工作记录聚合、
 * 能力挂载（SOP/知识/工具）、分桶记忆、员工定时任务、消息反馈、
 * SOP 资产版本链、演进提案生命周期。
 */
import { request } from "../../request";
import type { ExpertRecord } from "./experts";

// ---------------------------------------------------------------------------
// 类型（与后端 Pydantic 模型一一对应）
// ---------------------------------------------------------------------------

export type ResourceType = "sop" | "knowledge_base" | "tool";

export interface ResourceBinding {
  expert_id?: string;
  resource_type: ResourceType;
  resource_id: string;
  enabled?: boolean;
  seq?: number;
  metadata?: Record<string, unknown>;
}

export interface SopRecord {
  id: string;
  name: string;
  description?: string;
  business_domain?: string;
  goal?: string;
  nodes?: SopNode[];
  edges?: SopEdge[];
  slots?: SopSlot[];
  status: "draft" | "published" | "archived";
  version: number;
  owner_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SopNode {
  id: string;
  title: string;
  instruction?: string;
  expected_outcome?: string;
  tools?: string[];
}

export interface SopEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface SopSlot {
  key: string;
  label?: string;
  required?: boolean;
  ask_prompt?: string;
}

export interface SopVersion {
  sop_id: string;
  version: number;
  snapshot: Record<string, unknown>;
  change_note?: string;
  published_by?: string | null;
  created_at?: string | null;
}

export interface MemoryRecord {
  id: string;
  expert_id: string;
  user_id: string;
  kind: "profile" | "preference" | "fact";
  content: string;
  importance: number;
  dedup_key?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ScheduledTask {
  id: string;
  expert_id: string;
  name: string;
  description?: string;
  task_prompt: string;
  schedule_type: "cron" | "once";
  schedule_json: { cron?: string; run_at?: string } & Record<string, unknown>;
  timezone: string;
  status: "active" | "paused" | "completed" | "archived";
  cron_job_id?: string;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_status?: string;
  run_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TaskRun {
  id: string;
  task_id: string;
  expert_id: string;
  scheduled_for?: string | null;
  status: "running" | "succeeded" | "failed";
  result_summary?: string;
  error?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface TimelineEvent {
  kind: string;
  title: string;
  status: string;
  at?: string | null;
}

export interface WorkRecord {
  days: number;
  total_tasks: number;
  succeeded_tasks: number;
  feedback_up: number;
  feedback_down: number;
  positive_rate?: number | null;
  by_day: Array<{ date: string; tasks: number; feedback: number }>;
  timeline: TimelineEvent[];
}

export interface FeedbackSummary {
  days: number;
  feedback_up: number;
  feedback_down: number;
  total: number;
  positive_rate?: number | null;
  recent?: Array<{
    id: string;
    message_id: string;
    rating: "up" | "down";
    comment?: string;
    user_id?: string;
    created_at?: string | null;
  }>;
}

export interface EvolutionProposal {
  id: string;
  expert_id: string;
  title: string;
  trigger_type: "feedback" | "manual" | "audit";
  risk_level: "low" | "medium" | "high";
  hypothesis?: string;
  evidence?: Array<Record<string, unknown>>;
  candidate?: Record<string, unknown>;
  status:
    | "draft"
    | "ready_for_review"
    | "approved"
    | "rejected"
    | "published"
    | "rolled_back";
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CapabilityCounts {
  resources: number;
  skills: number;
  sops: number;
  scheduled_tasks: number;
}

export interface ApiKeyRecord {
  id: string;
  expert_id: string;
  name: string;
  key_prefix: string;
  created_by?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  /** 明文（仅签发响应返回一次）。 */
  plaintext?: string;
}

export interface PendingItem {
  kind: string;
  id: string;
  title: string;
  detail?: string;
  at?: string | null;
  link?: string;
}

const enc = encodeURIComponent;

// ---------------------------------------------------------------------------
// 专家维度
// ---------------------------------------------------------------------------

export const expertCapabilityApi = {
  /** 卡片网格批量计数（一次批查，无 N+1）。 */
  capabilityCounts: (expertIds: string[]) =>
    request<{ counts: Record<string, CapabilityCounts> }>(
      `/admin/experts-capability-counts?expert_ids=${enc(
        expertIds.join(","),
      )}`,
    ),

  /** 待办收件箱（P3：人工介入点统一聚合）。 */
  pendingItems: () =>
    request<{ items: PendingItem[]; counts: Record<string, number> }>(
      "/admin/pending-items",
    ),

  listApiKeys: (expertId: string) =>
    request<{ keys: ApiKeyRecord[] }>(
      `/admin/experts/${enc(expertId)}/api-keys`,
    ),

  issueApiKey: (expertId: string, name: string, expiresAt?: string) =>
    request<ApiKeyRecord>(`/admin/experts/${enc(expertId)}/api-keys`, {
      method: "POST",
      body: JSON.stringify({ name, expires_at: expiresAt || null }),
    }),

  revokeApiKey: (expertId: string, keyId: string) =>
    request<void>(
      `/admin/experts/${enc(expertId)}/api-keys/${enc(keyId)}`,
      { method: "DELETE" },
    ),

  /** 工作记录聚合（只读）。 */
  workRecord: (expertId: string, days = 30) =>
    request<WorkRecord>(
      `/admin/experts/${enc(expertId)}/work-record?days=${days}`,
    ),

  /** 能力挂载分组视图。 */
  listResources: (expertId: string) =>
    request<{
      bindings: Record<ResourceType, ResourceBinding[]>;
    }>(`/admin/experts/${enc(expertId)}/resources`),

  /** 整表替换能力挂载（空数组 = 清空）。 */
  replaceResources: (expertId: string, bindings: ResourceBinding[]) =>
    request<{ bindings: ResourceBinding[] }>(
      `/admin/experts/${enc(expertId)}/resources`,
      { method: "PUT", body: JSON.stringify({ bindings }) },
    ),

  listMemories: (expertId: string, kind = "", userId = "") =>
    request<{ memories: MemoryRecord[] }>(
      `/admin/experts/${enc(expertId)}/memories?kind=${enc(kind)}`
        + `&user_id=${enc(userId)}`,
    ),

  upsertMemory: (
    expertId: string,
    body: {
      user_id?: string;
      kind?: MemoryRecord["kind"];
      content: string;
      importance?: number;
      dedup_key?: string;
    },
  ) =>
    request<MemoryRecord>(`/admin/experts/${enc(expertId)}/memories`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteMemory: (expertId: string, memoryId: string) =>
    request<void>(
      `/admin/experts/${enc(expertId)}/memories/${enc(memoryId)}`,
      { method: "DELETE" },
    ),

  clearMemories: (expertId: string) =>
    request<void>(`/admin/experts/${enc(expertId)}/memories`, {
      method: "DELETE",
    }),

  listScheduledTasks: (expertId: string) =>
    request<{ tasks: ScheduledTask[] }>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks`,
    ),

  createScheduledTask: (
    expertId: string,
    body: {
      name: string;
      description?: string;
      task_prompt: string;
      schedule_type: "cron" | "once";
      schedule_json: Record<string, unknown>;
      timezone?: string;
    },
  ) =>
    request<ScheduledTask>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  updateScheduledTask: (
    expertId: string,
    taskId: string,
    body: {
      name?: string;
      description?: string;
      task_prompt?: string;
      schedule_json?: Record<string, unknown>;
      timezone?: string;
    },
  ) =>
    request<ScheduledTask>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),

  deleteScheduledTask: (expertId: string, taskId: string) =>
    request<void>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`,
      { method: "DELETE" },
    ),

  pauseScheduledTask: (expertId: string, taskId: string) =>
    request<ScheduledTask>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`
      + "/pause",
      { method: "POST" },
    ),

  resumeScheduledTask: (expertId: string, taskId: string) =>
    request<ScheduledTask>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`
      + "/resume",
      { method: "POST" },
    ),

  runScheduledTaskNow: (expertId: string, taskId: string) =>
    request<{ task_id: string; triggered: boolean }>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`
      + "/run-now",
      { method: "POST" },
    ),

  listTaskRuns: (expertId: string, taskId: string) =>
    request<{ runs: TaskRun[] }>(
      `/admin/experts/${enc(expertId)}/scheduled-tasks/${enc(taskId)}`
      + "/runs",
    ),

  feedbackSummary: (expertId: string, days = 30) =>
    request<FeedbackSummary>(
      `/admin/experts/${enc(expertId)}/feedback-summary?days=${days}`,
    ),
};

// ---------------------------------------------------------------------------
// SOP 资产
// ---------------------------------------------------------------------------

export const sopApi = {
  list: (status = "", q = "") =>
    request<SopRecord[]>(
      `/admin/sops?status=${enc(status)}&q=${enc(q)}`,
    ),

  get: (sopId: string) => request<SopRecord>(`/admin/sops/${enc(sopId)}`),

  create: (body: {
    name: string;
    description?: string;
    business_domain?: string;
    goal?: string;
    nodes?: SopNode[];
    edges?: SopEdge[];
    slots?: SopSlot[];
  }) =>
    request<SopRecord>("/admin/sops", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  update: (
    sopId: string,
    body: Partial<{
      name: string;
      description: string;
      business_domain: string;
      goal: string;
      nodes: SopNode[];
      edges: SopEdge[];
      slots: SopSlot[];
    }>,
  ) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  remove: (sopId: string) =>
    request<void>(`/admin/sops/${enc(sopId)}`, { method: "DELETE" }),

  publish: (sopId: string) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/publish`, {
      method: "POST",
    }),

  rollback: (sopId: string, toVersion: number) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ to_version: toVersion }),
    }),

  versions: (sopId: string) =>
    request<{ versions: SopVersion[] }>(
      `/admin/sops/${enc(sopId)}/versions`,
    ),

  archive: (sopId: string) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/archive`, {
      method: "POST",
    }),
};

// ---------------------------------------------------------------------------
// 演进提案
// ---------------------------------------------------------------------------

export const evolutionApi = {
  list: (expertId = "", status = "") =>
    request<{ proposals: EvolutionProposal[] }>(
      `/admin/evolution-proposals?expert_id=${enc(expertId)}`
      + `&status=${enc(status)}`,
    ),

  create: (body: {
    expert_id: string;
    title: string;
    trigger_type?: "feedback" | "manual" | "audit";
    risk_level?: "low" | "medium" | "high";
    hypothesis?: string;
    evidence?: Array<Record<string, unknown>>;
    candidate?: Record<string, unknown>;
  }) =>
    request<EvolutionProposal>("/admin/evolution-proposals", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  submit: (proposalId: string) =>
    request<EvolutionProposal>(
      `/admin/evolution-proposals/${enc(proposalId)}/submit`,
      { method: "POST" },
    ),

  review: (proposalId: string, action: "approve" | "reject") =>
    request<EvolutionProposal>(
      `/admin/evolution-proposals/${enc(proposalId)}/review`,
      { method: "POST", body: JSON.stringify({ action }) },
    ),

  publish: (proposalId: string) =>
    request<EvolutionProposal>(
      `/admin/evolution-proposals/${enc(proposalId)}/publish`,
      { method: "POST" },
    ),

  rollback: (proposalId: string) =>
    request<EvolutionProposal>(
      `/admin/evolution-proposals/${enc(proposalId)}/rollback`,
      { method: "POST" },
    ),
};

export type { ExpertRecord };
