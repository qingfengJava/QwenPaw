/**
 * admin/types.ts — shapes mirroring the M4 admin API (`routers/admin/*`).
 *
 * Field names match the backend pydantic models verbatim (snake_case).
 */

export interface AdminUserView {
  username: string;
  /** M1 flat role: "admin" | "employee". */
  role: string;
  display_name: string;
  disabled: boolean;
  created_at: string;
  /** M4 RBAC roles resolved for this user (flat mapping + explicit grants). */
  rbac_roles: string[];
  teams: string[];
}

export interface RoleRecord {
  name: string;
  permissions: string[];
  builtin: boolean;
  description: string;
}

export interface TeamRecord {
  name: string;
  members: string[];
  description: string;
}

/** ACL grant for one resource (agent or model); absent resource = unrestricted. */
export interface GrantRecord {
  roles: string[];
  users: string[];
  teams: string[];
  description: string;
}

export type QuotaSubjectType = "user" | "team" | "agent";
export type QuotaWindow = "minute" | "day";

export interface QuotaRule {
  subject_type: QuotaSubjectType;
  subject: string;
  model: string;
  window: QuotaWindow;
  limit: number;
  description: string;
}

export interface AuditEventView {
  ts: number;
  workspace_dir: string;
  agent_id: string;
  session_id: string;
  tool_name: string;
  target: string;
  decision: string;
  reason: string;
  actor_id: string;
}

export interface AuditPage {
  events: AuditEventView[];
  total: number;
}

export type KbScope = "personal" | "team" | "enterprise";

export interface KnowledgeBase {
  id: string;
  name: string;
  scope: KbScope;
  owner_id: string;
  team_id: string;
  description: string;
  grants_roles: string[];
  grants_users: string[];
  grants_teams: string[];
  created_at: string;
}

export interface KbDocumentView {
  doc_id: string;
  title: string;
  source: string;
  chunk_count: number;
  created_at: string;
}
