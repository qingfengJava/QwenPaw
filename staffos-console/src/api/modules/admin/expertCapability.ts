/**
 * admin/expertCapability.ts — 数字员工能力层客户端（20260830）。
 *
 * 对应后端 `routers/admin/expert_capability.py`：工作记录聚合、
 * 能力挂载（SOP/知识/工具）、分桶记忆、员工定时任务、消息反馈、
 * SOP 资产版本链、演进提案生命周期。
 */
import { request } from "../../request";
import { getApiUrl } from "../../config";
import { buildAuthHeaders } from "../../authHeaders";
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
  /** 环境: draft-调试草稿, production-线上发布（对齐 agent_documents） */
  environment?: "draft" | "production";
  created_at?: string | null;
  updated_at?: string | null;
}

/** SOP 实时编辑事件（AI tool / 画布保存后后端向 SSE topic 广播的全量快照）。
 *
 * 员工级面板流（streamExpertEvents）只发轻量索引事件：不含
 * goal/nodes/edges/slots 图数据，仅用于感知 created 开画布与刷列表。
 */
export interface SopLiveEvent {
  action: "created" | "updated" | "published";
  sop_id: string;
  environment: "draft" | "production";
  version: number;
  name: string;
  goal?: string;
  nodes?: SopNode[];
  edges?: SopEdge[];
  slots?: SopSlot[];
  owner_id?: string;
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
  /** 任务来源: ui-界面创建, chat-对话创建, api-开放接口创建 */
  source?: "ui" | "chat" | "api";
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
  /** 关联 agent_runs 的运行 ID（详情跳转键；历史行可能为空） */
  run_id?: string;
  /** 本次执行落库的会话 ID */
  session_id?: string;
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

/**
 * 手动读一条 SSE 流并按帧回调（EventSource 不能带自定义鉴权 header，
 * 与 streamBackupJob 同款）；onEvent 每收到一条 data 帧回调一次，
 * signal 中止时流自然结束。回调异常不影响后续帧。
 */
async function readSopEventStream(
  url: string,
  onEvent: (event: SopLiveEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    headers: { ...buildAuthHeaders(), Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `SSE connection failed: ${res.status}`);
  }
  if (!res.body) throw new Error("No SOP event stream received");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // 逐块读取 → 按 SSE 帧分隔符（空行）切分 → 仅消费 data: 帧
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      try {
        const parsed = JSON.parse(dataLine.slice(6)) as {
          event?: SopLiveEvent;
        };
        if (parsed.event) onEvent(parsed.event);
      } catch {
        // 心跳/非 JSON 帧忽略
      }
    }
  }
}

export const sopApi = {
  list: (status = "", q = "", ownerId = "", full = false, environment = "") =>
    request<SopRecord[]>(
      `/admin/sops?status=${enc(status)}&q=${enc(q)}`
      + `&owner_id=${enc(ownerId)}&full=${full}&environment=${enc(environment)}`,
    ),

  get: (sopId: string, environment = "draft") =>
    request<SopRecord>(
      `/admin/sops/${enc(sopId)}?environment=${enc(environment)}`,
    ),

  /** 存量线上 SOP 首次编辑：fork 出可编辑草稿行（无则新建）。 */
  ensureDraft: (sopId: string) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/ensure-draft`, {
      method: "POST",
    }),

  create: (body: {
    name: string;
    description?: string;
    business_domain?: string;
    goal?: string;
    nodes?: SopNode[];
    edges?: SopEdge[];
    slots?: SopSlot[];
    /** 归属员工 id（SOP 私有能力化：员工页新建必传） */
    owner_expert_id?: string;
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
    environment = "draft",
  ) =>
    request<SopRecord>(
      `/admin/sops/${enc(sopId)}?environment=${enc(environment)}`,
      {
        method: "PATCH",
        body: JSON.stringify(body),
      },
    ),

  remove: (sopId: string) =>
    request<void>(`/admin/sops/${enc(sopId)}`, { method: "DELETE" }),

  publish: (sopId: string, expertId = "") =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/publish`, {
      method: "POST",
      body: JSON.stringify(expertId ? { expert_id: expertId } : {}),
    }),

  duplicate: (sopId: string, targetExpertId: string) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ target_expert_id: targetExpertId }),
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

  /**
   * 订阅一条 SOP 的实时编辑流（AI tool / 画布保存后全量快照）。
   */
  streamEvents: (
    sopId: string,
    onEvent: (event: SopLiveEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> =>
    readSopEventStream(
      getApiUrl(`/admin/sops/${enc(sopId)}/events`),
      onEvent,
      signal,
    ),

  /**
   * 订阅一位员工的 SOP 活动流（轻量索引事件，不含图数据）。
   *
   * AI 对话新建 SOP 时前端尚不知 sop_id；面板/外壳订阅本流感知 created
   * 后自动打开画布（画布内再由 streamEvents 接管实时重绘），
   * updated/published 用于刷新列表与状态胶囊。
   *
   * 固定 ?replay=false：自动开画布是副作用，必须跳过事件总线对历史
   * created 的缓冲重放，否则一进入工作台/详情页就会误开画布。
   */
  streamExpertEvents: (
    expertId: string,
    onEvent: (event: SopLiveEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> =>
    readSopEventStream(
      getApiUrl(`/admin/experts/${enc(expertId)}/sops/events?replay=false`),
      onEvent,
      signal,
    ),
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

// ---------------------------------------------------------------------------
// 归因桶热力（缺口③消费面）+ open API 审计（缺口②消费面）
// ---------------------------------------------------------------------------

export interface AttributionHeatmap {
  days: number;
  buckets: string[];
  dates: string[];
  matrix: Record<string, Record<string, number>>;
  totals: Record<string, number>;
  top_experts: Array<{ expert_id: string; name: string; count: number }>;
  total: number;
}

export interface OpenApiAuditRow {
  id: string;
  key_id: string;
  expert_id: string;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  idem_key: string;
  client_ip: string;
  created_at?: string | null;
}

export const attributionApi = {
  heatmap: (days = 30, expertId = "") =>
    request<AttributionHeatmap>(
      `/admin/attribution-heatmap?days=${days}&expert_id=${enc(expertId)}`,
    ),
};

export const openApiAuditApi = {
  list: (keyId = "", expertId = "", limit = 50) =>
    request<{ rows: OpenApiAuditRow[]; count: number }>(
      `/admin/open-api/audit?key_id=${enc(keyId)}`
      + `&expert_id=${enc(expertId)}&limit=${limit}`,
    ),
};

export type { ExpertRecord };
