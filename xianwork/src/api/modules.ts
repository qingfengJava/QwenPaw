/**
 * XianWork API surface: Xian routes + reused console/auth/chats routes.
 */
import { request } from "./request";

// ---------------------------------------------------------------------------
// shared types
// ---------------------------------------------------------------------------

export interface AIBinding {
  kind: "expert" | "expert_team";
  ref_id: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: string;
  department_id: string | null;
  ai_binding: AIBinding;
  template_tag: string;
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
}

export interface ExpertTeam {
  id: string;
  name: string;
  description: string;
  mode: string;
  version: number;
  agent_id: string;
  member_count: number;
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
    ai_binding?: AIBinding;
  }) =>
    request<Project>("/xian/projects", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (
    id: string,
    body: Partial<Pick<Project, "name" | "description" | "status">> & {
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
    body: { title: string; description?: string; assignee?: string },
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

export const expertApi = {
  list: () => request<Expert[]>("/xian/experts"),
  listTeams: () => request<ExpertTeam[]>("/xian/experts/teams"),
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
}

export const chatApi = {
  list: () => request<ChatSpecView[]>("/chats?archived=false"),
  create: (name = "New Chat") =>
    request<ChatSpecView>("/chats", {
      method: "POST",
      body: JSON.stringify({
        name,
        session_id: `console:${Date.now()}`,
        user_id: "local",
      }),
    }),
  history: (chatId: string) =>
    request<{ messages: unknown[] }>(`/chats/${enc(chatId)}/history`),
};
