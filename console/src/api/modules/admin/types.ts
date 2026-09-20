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
  /** Custom avatar URL; empty = front-end DiceBear fallback. */
  avatar: string;
  disabled: boolean;
  created_at: string;
  /** Organization (tenant) the account belongs to. */
  org_id: string;
  /** M4 RBAC roles resolved for this user (flat mapping + explicit grants). */
  rbac_roles: string[];
  teams: string[];
  /** 员工档案：真实姓名。 */
  real_name: string;
  /** 员工档案：手机号。 */
  phone: string;
  /** 员工档案：性别 0未知/1男/2女。 */
  gender: number;
  /** 员工档案：职位。 */
  position: string;
  /** 超管标记：true 时禁止被禁用/删除/降级。 */
  is_superadmin: boolean;
  /** 归属部门名称列表（后端批量组装）。 */
  department_names: string[];
}

/** One channel-identity → account binding (admin identity-bindings page). */
export interface IdentityBindingView {
  channel: string;
  external_user_id: string;
  username: string;
}

export interface RoleRecord {
  name: string;
  permissions: string[];
  builtin: boolean;
  description: string;
  /** 角色显示名（角色工作台列表主展示）。 */
  display_name?: string;
  /** 默认数据范围。 */
  data_scope?: string;
  sort_order?: number;
  is_enabled?: boolean;
}

/** 角色-员工列表 tab 的一行成员。 */
export interface RoleMemberView {
  username: string;
  real_name: string;
  phone: string;
  display_name: string;
  disabled: boolean;
  department_names: string[];
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
  /** 知识生命周期状态（0046；T3 起携带，缺省回退 published）。 */
  knowledge_status?: string;
  valid_from?: string | null;
  valid_to?: string | null;
  created_at: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// M7 PG-RBAC: Menu, Permission, DataScope records
// ─────────────────────────────────────────────────────────────────────────────

/** Menu record as returned by the M7 backend (`GET /admin/menus`). */
export interface MenuRecord {
  id: string;
  parent_id: string | null;
  name: string;
  menu_type: "directory" | "menu" | "button";
  path: string;
  component: string;
  icon: string;
  perm_code: string;
  sort_order: number;
  is_visible: boolean;
  is_enabled: boolean;
  is_external: boolean;
  redirect: string;
  children?: MenuRecord[];
}
