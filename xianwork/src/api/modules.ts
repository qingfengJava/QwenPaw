/**
 * XianWork API surface: Xian routes + reused console/auth/chats routes.
 */
import { ApiError, authHeaders, request } from "./request";

// ---------------------------------------------------------------------------
// shared types
// ---------------------------------------------------------------------------

export interface AIBinding {
  kind: "expert" | "expert_team";
  ref_id: string;
}

/** 运营位条目：任务模板（详情页点击即以 prompt 召唤/发起 run）。 */
export interface ExpertSampleTask {
  title: string;
  prompt: string;
}

/** 运营位条目：静态使用案例（团队详情另叠加真实「最近交付」投影）。 */
export interface ExpertShowcaseItem {
  title: string;
  desc: string;
  tags?: string[];
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: string;
  department_id: string | null;
  ai_binding: AIBinding;
  template_tag: string;
  instructions: string;
  created_by: string;
  member_role: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: "todo" | "doing" | "paused" | "done";
  assignee: string | null;
  creator: string;
  chat_id: string | null;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FeedEvent {
  id: number;
  project_id: string;
  actor: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
}

export interface Expert {
  id: string;
  name: string;
  icon: string;
  description: string;
  version: number;
  agent_id: string;
  /** Catalog fields (market plane; additive — old fields unchanged). */
  status?: string;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  owner_id?: string | null;
  visibility?: string;
  is_builtin?: boolean;
  usage_count?: number;
  featured?: boolean;
  /** 详情页「专家帮你做」任务模板（管理端/内置出厂配置）。 */
  sample_tasks?: ExpertSampleTask[];
  /** 详情页「使用案例」静态运营位。 */
  showcase?: ExpertShowcaseItem[];
  updated_at?: string | null;
}

export interface ExpertSkillBindingView {
  expert_id: string;
  skill_name: string;
  enabled: boolean;
  seq: number;
}

export interface ExpertDetail extends Expert {
  system_prompt?: string;
  skills?: ExpertSkillBindingView[];
  teams?: { id: string; name: string; mode: string }[];
}

export interface ExpertCategory {
  key: string;
  label: string;
  icon: string;
}

export interface ExpertTeamMemberView {
  expert_id: string;
  name: string;
  title: string;
  icon: string;
  role_hint: string;
  member_role: string;
}

export interface ExpertTeam {
  id: string;
  name: string;
  description: string;
  mode: string;
  version: number;
  agent_id: string;
  member_count: number;
  category?: string;
  tags?: string[];
  members?: ExpertTeamMemberView[];
  /** 详情页「任务示例」模板（点击即以 prompt 为 goal 发起 run）。 */
  sample_tasks?: ExpertSampleTask[];
  /** 详情页「使用案例」静态运营位。 */
  showcase?: ExpertShowcaseItem[];
}

export interface ChatSummary {
  id: string;
  name: string;
  status: string;
  updated_at: string;
  project_id?: string;
}

export interface ProjectMember {
  project_id: string;
  username: string;
  role: "owner" | "editor" | "viewer";
}

// ---------------------------------------------------------------------------
// auth (reuses the backend auth endpoints)
// ---------------------------------------------------------------------------

export const authApi = {
  login: (username: string, password: string) =>
    request<{ token: string; role: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  status: () =>
    request<{ enabled: boolean; has_users: boolean }>("/auth/status"),
};

// ---------------------------------------------------------------------------
// projects / tasks / feed (XianWork plane)
// ---------------------------------------------------------------------------

const enc = encodeURIComponent;

export const projectApi = {
  list: (templates = false) =>
    request<Project[]>(`/xian/projects${templates ? "?templates=true" : ""}`),
  get: (id: string) => request<Project>(`/xian/projects/${enc(id)}`),
  create: (body: {
    name: string;
    description?: string;
    instructions?: string;
    ai_binding?: AIBinding;
  }) =>
    request<Project>("/xian/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (
    id: string,
    body: Partial<
      Pick<Project, "name" | "description" | "status" | "instructions">
    > & {
      ai_binding?: AIBinding;
    },
  ) =>
    request<Project>(`/xian/projects/${enc(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    request<void>(`/xian/projects/${enc(id)}`, { method: "DELETE" }),
  members: (id: string) =>
    request<ProjectMember[]>(`/xian/projects/${enc(id)}/members`),
  addMember: (id: string, username: string, role = "viewer") =>
    request<void>(`/xian/projects/${enc(id)}/members`, {
      method: "POST",
      body: JSON.stringify({ username, role }),
    }),
  updateMemberRole: (id: string, username: string, role: string) =>
    request<void>(`/xian/projects/${enc(id)}/members/${enc(username)}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),
  removeMember: (id: string, username: string) =>
    request<void>(
      `/xian/projects/${enc(id)}/members/${enc(username)}`,
      { method: "DELETE" },
    ),
  createFromTemplate: (tag: string) =>
    request<Project>(`/xian/projects/from-template/${enc(tag)}`, {
      method: "POST",
    }),
  feed: (id: string, beforeId = 0, limit = 50) =>
    request<FeedEvent[]>(
      `/xian/projects/${enc(id)}/feed?before_id=${beforeId}&limit=${limit}`,
    ),
  comment: (id: string, text: string) =>
    request<void>(`/xian/projects/${enc(id)}/comments`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  projectChats: (id: string) =>
    request<ChatSummary[]>(`/xian/projects/${enc(id)}/chats`),
};

export const taskApi = {
  list: (projectId: string) =>
    request<Task[]>(`/xian/projects/${enc(projectId)}/tasks`),
  create: (
    projectId: string,
    body: {
      title: string;
      description?: string;
      assignee?: string;
      status?: Task["status"];
    },
  ) =>
    request<Task>(`/xian/projects/${enc(projectId)}/tasks`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (
    projectId: string,
    taskId: string,
    body: Partial<Pick<Task, "status" | "sort_order" | "assignee" | "title">>,
  ) =>
    request<Task>(
      `/xian/projects/${enc(projectId)}/tasks/${enc(taskId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(body),
      },
    ),
  remove: (projectId: string, taskId: string) =>
    request<void>(
      `/xian/projects/${enc(projectId)}/tasks/${enc(taskId)}`,
      { method: "DELETE" },
    ),
};

export interface ExpertListParams {
  category?: string;
  q?: string;
  sort?: "composite" | "hot" | "new";
  scope?: "all" | "mine";
}

export interface ExpertCreatePayload {
  name: string;
  icon?: string;
  description?: string;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  system_prompt?: string;
  visibility?: "org" | "private";
  skills?: { skill_name: string; enabled?: boolean; seq?: number }[];
}

export interface ExpertUpdatePayload {
  name?: string;
  icon?: string;
  description?: string;
  title?: string;
  category?: string;
  badge?: string;
  tags?: string[];
  system_prompt?: string;
  visibility?: "org" | "private";
}

const expertQuery = (params: ExpertListParams) => {
  const usp = new URLSearchParams();
  if (params.category) usp.set("category", params.category);
  if (params.q) usp.set("q", params.q);
  if (params.sort) usp.set("sort", params.sort);
  if (params.scope) usp.set("scope", params.scope);
  const qs = usp.toString();
  return qs ? `?${qs}` : "";
};

export const expertApi = {
  /** Market list (published + visible) or the caller's own experts. */
  list: (params: ExpertListParams = {}) =>
    request<Expert[]>(`/xian/experts${expertQuery(params)}`),
  /** My experts across every status (custom-expert management). */
  mine: (params: Omit<ExpertListParams, "scope"> = {}) =>
    request<Expert[]>(`/xian/experts${expertQuery({ ...params, scope: "mine" })}`),
  detail: (id: string) =>
    request<ExpertDetail>(`/xian/experts/${enc(id)}`),
  categories: () => request<ExpertCategory[]>("/xian/experts/categories"),
  listTeams: (category = "") =>
    request<ExpertTeam[]>(
      `/xian/experts/teams${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  /** Summon counter — fire-and-forget from the market card. */
  use: (id: string) =>
    request<{ expert_id: string; agent_id: string; usage_count: number }>(
      `/xian/experts/${enc(id)}/use`,
      { method: "POST" },
    ),
  /** Create a personal expert (backend publishes it immediately). */
  create: (body: ExpertCreatePayload) =>
    request<ExpertDetail>("/xian/experts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (id: string, body: ExpertUpdatePayload) =>
    request<ExpertDetail>(`/xian/experts/${enc(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    request<void>(`/xian/experts/${enc(id)}`, { method: "DELETE" }),
  setSkills: (
    id: string,
    skills: { skill_name: string; enabled?: boolean; seq?: number }[],
  ) =>
    request<ExpertDetail>(`/xian/experts/${enc(id)}/skills`, {
      method: "PUT",
      body: JSON.stringify({ skills }),
    }),
};

// ---------------------------------------------------------------------------
// collaboration extras (directory / resources / bindings / automations)
// ---------------------------------------------------------------------------

export interface DirectoryUser {
  username: string;
  display_name: string;
  department_id: string | null;
  department_name: string;
  role: string;
  is_self: boolean;
}

export interface DepartmentNode {
  id: string;
  parent_id: string | null;
  name: string;
  path: string;
  description: string;
  children: DepartmentNode[];
}

export interface SkillView {
  name: string;
  description: string;
  version: string;
  enabled: boolean;
}

export interface ConnectorView {
  client_key: string;
  display_name: string;
  description: string;
  transport: string;
  enabled: boolean;
}

export interface ProjectBinding {
  id: string;
  project_id: string;
  kind: "connector" | "skill";
  ref_id: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

export interface ProjectAutomation {
  id: string;
  project_id: string;
  name: string;
  schedule: string;
  prompt: string;
  enabled: boolean;
  cron_job_id: string | null;
  last_run_at: string | null;
  next_run_at?: string | null;
}

export const directoryApi = {
  users: (q = "", department = "") =>
    request<DirectoryUser[]>(
      `/xian/directory/users?q=${encodeURIComponent(q)}` +
        (department ? `&department=${encodeURIComponent(department)}` : ""),
    ),
  departments: () => request<DepartmentNode[]>("/xian/directory/departments"),
};

export const resourceApi = {
  skills: () => request<SkillView[]>("/xian/resources/skills"),
  connectors: () => request<ConnectorView[]>("/xian/resources/connectors"),
};

export const bindingApi = {
  list: (projectId: string) =>
    request<ProjectBinding[]>(`/xian/projects/${enc(projectId)}/bindings`),
  add: (
    projectId: string,
    body: { kind: "connector" | "skill"; ref_id: string; enabled?: boolean },
  ) =>
    request<ProjectBinding>(`/xian/projects/${enc(projectId)}/bindings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  remove: (projectId: string, bindingId: string) =>
    request<void>(
      `/xian/projects/${enc(projectId)}/bindings/${enc(bindingId)}`,
      { method: "DELETE" },
    ),
};

export const automationApi = {
  list: (projectId: string) =>
    request<ProjectAutomation[]>(
      `/xian/projects/${enc(projectId)}/automations`,
    ),
  create: (
    projectId: string,
    body: {
      name: string;
      schedule: string;
      prompt?: string;
      enabled?: boolean;
      timezone?: string;
    },
  ) =>
    request<ProjectAutomation>(
      `/xian/projects/${enc(projectId)}/automations`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
  remove: (projectId: string, automationId: string) =>
    request<void>(
      `/xian/projects/${enc(projectId)}/automations/${enc(automationId)}`,
      { method: "DELETE" },
    ),
};

// ---------------------------------------------------------------------------
// personal chats (console plane; owner isolation enforced server-side)
// ---------------------------------------------------------------------------

export interface ChatSpecView {
  id: string;
  name: string;
  status: string;
  updated_at: string;
  pinned: boolean;
  session_id: string;
  channel?: string;
  user_id?: string;
  created_at?: string | null;
  /** Full spec dump from the workspace grouping endpoint (path binding). */
  meta?: Record<string, unknown> | null;
}

export const chatApi = {
  /** Console-channel chats of one user — same scope the backend chat page sees. */
  list: (userId: string) =>
    request<ChatSpecView[]>(
      `/chats?channel=console${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}&archived=false`,
    ),
  create: (name: string, userId: string) =>
    request<ChatSpecView>("/chats", {
      method: "POST",
      body: JSON.stringify({
        name,
        channel: "console",
        session_id: `console:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
        user_id: userId,
      }),
    }),
  /** GET /chats/{id} returns `{ messages, status }` (no /history suffix). */
  history: (chatId: string) => request<{ messages: unknown[]; status?: string }>(`/chats/${enc(chatId)}`),
  rename: (chatId: string, name: string) =>
    request<ChatSpecView>(`/chats/${enc(chatId)}`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  togglePin: (chatId: string, pinned: boolean) =>
    request<ChatSpecView>(`/chats/${enc(chatId)}`, {
      method: "PUT",
      body: JSON.stringify({ pinned }),
    }),
  remove: (chatId: string) => request<{ success: boolean }>(`/chats/${enc(chatId)}`, { method: "DELETE" }),
  /** Batch delete (backend takes a bare JSON array of ids). */
  batchRemove: (chatIds: string[]) =>
    request<{ deleted: boolean }>("/chats/batch-delete", {
      method: "POST",
      body: JSON.stringify(chatIds),
    }),
  /** Batch archive (running chats are skipped server-side). */
  batchArchive: (chatIds: string[]) =>
    request<{ succeeded: string[]; failed: { chat_id: string; reason: string }[] }>(
      "/chats/actions/batch-archive",
      {
        method: "POST",
        body: JSON.stringify({ chat_ids: chatIds }),
      },
    ),
  /** Ask the backend to cancel the running turn for this chat. */
  stop: (chatId: string) =>
    request<void>(`/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`, { method: "POST" }),
  /** Upload one attachment (image/file) to the console plane.
   *
   * With `chatId` the backend stores the file under the chat's effective
   * project directory (`{project_dir}/media/`), next to agent-generated
   * files; `url` is then an absolute `file://` URI. Without it the legacy
   * channel media_dir behavior (bare stored name) is unchanged. */
  upload: async (
    file: File,
    chatId?: string,
  ): Promise<{
    url: string;
    stored_name?: string;
    file_name?: string;
    size?: number;
  }> => {
    const formData = new FormData();
    formData.append("file", file);
    if (chatId) {
      formData.append("chat_id", chatId);
    }
    const res = await fetch("/api/console/upload", {
      method: "POST",
      headers: authHeaders() as Record<string, string>,
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`上传失败: ${res.status} ${text.slice(0, 120)}`);
    }
    return res.json();
  },
};

/* ------------------------------------------------------------------
 * Share links — capability URLs minted by the backend (xian_shares).
 * ------------------------------------------------------------------ */

export interface ShareLink {
  token: string;
  /** Relative SPA path, e.g. `/xianwork/share/{token}`. */
  url: string;
}

export interface ShareFileItem {
  stored_name: string;
  file_name: string | null;
  media_type: string | null;
  size: number | null;
  source: string | null;
  url: string;
}

export interface ShareView {
  token: string;
  chat: {
    id: string;
    name: string;
    created_at: string;
    updated_at: string;
  };
  shared_at: string;
  messages: unknown[];
  files: ShareFileItem[];
}

export const shareApi = {
  /** POST /xian/shares — mint (or reuse) the share link for one chat. */
  create: (chatId: string) =>
    request<ShareLink>("/xian/shares", {
      method: "POST",
      body: JSON.stringify({ chat_id: chatId }),
    }),
  /** Public share view — plain fetch on purpose: the token IS the
   * credential (usable in a logged-out browser), so no auth header and
   * no 401 → login redirect handling. */
  view: async (token: string): Promise<ShareView> => {
    const res = await fetch(
      `/api/xian/shares/view/${encodeURIComponent(token)}`,
      { headers: { Accept: "application/json" } },
    );
    if (!res.ok) {
      throw new ApiError(
        res.status,
        res.status === 404 ? "分享不存在或已失效" : "加载分享失败",
      );
    }
    return (await res.json()) as ShareView;
  },
};

/* ------------------------------------------------------------------
 * Workforce team runs — the two-level Harness orchestration plane
 * (POST /xian/workforce/runs; see backend app/workforce).
 * ------------------------------------------------------------------ */

/** run 状态机值（与后端 contracts.RUN_STATUS_* 对齐）。 */
export type TeamRunStatus =
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

/** 节点状态机值。 */
export type TeamNodeStatus =
  | "pending"
  | "delegated"
  | "running"
  | "verifying"
  | "repairing"
  | "done"
  | "failed";

export interface TeamRunNode {
  run_id: string;
  node_key: string;
  assignee_expert_id: string;
  /** 跨用户移交：接管者用户（null=团队内成员）。 */
  assignee_user_id: string | null;
  node_type: "task" | "repair" | "integration" | "final" | "clarify";
  status: TeamNodeStatus;
  contract: Record<string, unknown>;
  result: Record<string, unknown>;
  repair: Record<string, unknown>;
  verdict: "" | "PASS" | "FAIL" | "ESCALATE";
  repair_count: number;
  session_id: string;
  token_cost: number;
  attempt: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TeamRun {
  id: string;
  team_id: string;
  project_id: string | null;
  source_chat_id: string | null;
  initiator_id: string;
  status: TeamRunStatus;
  goal: string;
  plan: { nodes?: unknown[]; plan_note?: string; source?: string };
  policy: Record<string, unknown>;
  context_version: number;
  summary: string;
  result: Record<string, unknown>;
  clarification: { questions?: string[]; options?: Record<string, string[]>; answers?: Record<string, string> };
  repair_count: number;
  replan_count: number;
  error: string;
  escalation_reason: string;
  created_at?: string | null;
  updated_at?: string | null;
  /** 详情接口附带；列表接口无此字段。 */
  nodes?: TeamRunNode[];
}

export interface TeamRunCreateBody {
  team_id: string;
  goal: string;
  source_chat_id?: string;
  project_id?: string;
  // 刻意无 policy：熔断策略是治理面配置（团队 orchestration.policy），
  // 员工请求体不可覆盖——后端已拒绝该字段。
}

export const workforceApi = {
  /** 创建并后台启动一次专家团任务（三通道共用）。 */
  create: (body: TeamRunCreateBody) =>
    request<TeamRun>("/xian/workforce/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** 个人维度：自己发起的 run；project_id 维度：项目全量（需成员）。 */
  list: (params: { team_id?: string; project_id?: string; status?: string } = {}) => {
    const usp = new URLSearchParams();
    if (params.team_id) usp.set("team_id", params.team_id);
    if (params.project_id) usp.set("project_id", params.project_id);
    if (params.status) usp.set("status", params.status);
    const qs = usp.toString();
    return request<TeamRun[]>(`/xian/workforce/runs${qs ? `?${qs}` : ""}`);
  },
  /** 详情：DAG 计划 + 全部节点留痕（契约/结果/裁决/返工）。 */
  detail: (runId: string) =>
    request<TeamRun>(`/xian/workforce/runs/${enc(runId)}`),
  /** 取消运行中的任务（终态幂等）。 */
  cancel: (runId: string) =>
    request<{ status: string }>(`/xian/workforce/runs/${enc(runId)}/cancel`, {
      method: "POST",
    }),
  /** 续跑中断任务（从已完成节点之后恢复）。 */
  resume: (runId: string) =>
    request<{ status: string }>(`/xian/workforce/runs/${enc(runId)}/resume`, {
      method: "POST",
    }),
  /** 答复澄清问题（awaiting_confirm 状态输入）。 */
  clarify: (runId: string, answers: Record<string, string>) =>
    request<{ status: string; context_version: number }>(
      `/xian/workforce/runs/${enc(runId)}/clarify`,
      { method: "POST", body: JSON.stringify({ answers }) },
    ),
  /** 人工裁决熔断节点（retry 放行 / abort 终止）。 */
  resolveEscalation: (
    runId: string,
    nodeKey: string,
    action: "retry" | "abort",
    note = "",
  ) =>
    request<{ status: string }>(
      `/xian/workforce/runs/${enc(runId)}/nodes/${enc(nodeKey)}/escalation`,
      { method: "POST", body: JSON.stringify({ action, note }) },
    ),
  /** 跨用户移交（项目组内数字员工协同；上下文版本延续）。 */
  handover: (
    runId: string,
    nodeKey: string,
    body: { target_user_id: string; target_expert_id: string; handover_note?: string },
  ) =>
    request<{ node_key: string; assignee_user_id: string }>(
      `/xian/workforce/runs/${enc(runId)}/nodes/${enc(nodeKey)}/handover`,
      { method: "POST", body: JSON.stringify(body) },
    ),
};

/* ------------------------------------------------------------------
 * Provider / model plane — mirrors the backend ModelSelector contract.
 * ------------------------------------------------------------------ */

export interface ModelInfo {
  id: string;
  name: string;
  supports_multimodal?: boolean | null;
  supports_image?: boolean | null;
  supports_video?: boolean | null;
  is_free?: boolean;
  max_input_length?: number;
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: ModelInfo[];
  extra_models?: ModelInfo[];
  is_custom?: boolean;
  is_local?: boolean;
  require_api_key?: boolean;
  api_key?: string;
  base_url?: string;
  is_free_tier?: boolean;
  supports_oauth?: boolean;
  oauth_connected?: boolean;
}

export interface ActiveModelsInfo {
  active_llm?: { provider_id: string; model: string };
  effective_max_input_length?: number | null;
}

export const providerApi = {
  list: () => request<ProviderInfo[]>("/models"),
  active: (agentId: string) =>
    request<ActiveModelsInfo>(
      `/models/active?scope=effective${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""}`,
    ),
  /** Switch the active LLM for one agent (same slot API the console uses). */
  setActive: (providerId: string, model: string, agentId: string) =>
    request<ActiveModelsInfo>("/models/active", {
      method: "PUT",
      body: JSON.stringify({
        provider_id: providerId,
        model,
        scope: "agent",
        agent_id: agentId,
      }),
    }),
};

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

export const agentApi = {
  list: () => request<{ agents: AgentSummary[] }>("/agents"),
};

export interface LoopModeInfo {
  id: string;
  name: string;
  slash_command: string;
  description: string;
  source: "builtin" | "custom" | "plugin";
  /** Plugin-owned display names keyed by locale (e.g. zh-CN), console parity. */
  name_i18n?: Record<string, string> | null;
  description_i18n?: Record<string, string> | null;
}

export const loopApi = {
  list: () => request<LoopModeInfo[]>("/loops"),
};

// ---------------------------------------------------------------------------
// workspaces (XianWork plane; path binding via chats.meta.runtime_context)
// ---------------------------------------------------------------------------

export interface WorkspaceView {
  id: string;
  name: string;
  dir_path: string;
  created_at?: string | null;
  updated_at?: string | null;
  chats_count?: number;
  /** Only present with includeChats=true (server-side grouping). */
  chats?: ChatSpecView[];
}

export interface WorkspaceListResult {
  workspaces: WorkspaceView[];
  unbound_chats: ChatSpecView[];
}

export const workspaceApi = {
  /** One call returns workspaces + server-grouped chats (frontend never
   *  compares paths — Windows case/separator pitfalls stay server-side). */
  list: (includeChats = false) =>
    request<WorkspaceListResult>(
      `/xian/workspaces${includeChats ? "?include_chats=true" : ""}`,
    ),
  /** Native OS directory picker (server-local desktop). `path` is null
   *  when the user cancels; 503 on headless/remote deployments. */
  pickDirectory: () =>
    request<{ path: string | null }>("/xian/workspaces/pick-directory", {
      method: "POST",
    }),
  /** Register a disk directory; `create` mkdirs it first when missing. */
  create: (body: { name: string; dir_path: string; create?: boolean }) =>
    request<WorkspaceView>("/xian/workspaces", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** Rename only — the on-disk directory is never touched. */
  update: (id: string, name: string) =>
    request<WorkspaceView>(`/xian/workspaces/${enc(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  /** Deletes the registry row and unbinds its chats; disk stays intact. */
  remove: (id: string) =>
    request<{ deleted: boolean; unbound_chats: number }>(
      `/xian/workspaces/${enc(id)}`,
      { method: "DELETE" },
    ),
  /** Batch bind chats (effective from the next turn; running → 409). */
  bindChats: (id: string, chatIds: string[]) =>
    request<{ bound: number }>(`/xian/workspaces/${enc(id)}/chats`, {
      method: "PUT",
      body: JSON.stringify({ chat_ids: chatIds }),
    }),
  /** Clear one chat's directory override (falls back to agent default). */
  unbindChat: (id: string, chatId: string) =>
    request<{ unbound: boolean }>(
      `/xian/workspaces/${enc(id)}/chats/${enc(chatId)}`,
      { method: "DELETE" },
    ),
  /** Open the folder in the host explorer; remote deployments 409. */
  openFolder: (id: string) =>
    request<{ opened: boolean; path: string }>(
      `/xian/workspaces/${enc(id)}/open-folder`,
      { method: "POST" },
    ),
};

// ---------------------------------------------------------------------------
// filesystem browsing (reuses the console project-directory browse API)
// ---------------------------------------------------------------------------

export interface BrowseDirsResult {
  current: string;
  parent: string | null;
  dirs: { name: string; path: string }[];
}

export const fsApi = {
  /** List subdirectories of one server path; "/" on Windows lists drives. */
  browseDirs: (path: string) =>
    request<BrowseDirsResult>(
      `/workspace/project-directory/browse-dirs?path=${encodeURIComponent(path)}`,
    ),
};
