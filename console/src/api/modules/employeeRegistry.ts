/**
 * api/modules/employeeRegistry.ts — 数字员工注册表与治理接口客户端。
 *
 * 对应后端 `src/qwenpaw/app/employees/`：注册表是「智能体 / 数字员工 /
 * 专家团」三形态 + 归属部门 + 可见范围的统一读面，治理写接口是唯一入口
 * （写权威表 employee_governance 并投影到 RBAC agent_grants）。
 */
import { request } from "../request";

/** 员工形态：原生智能体 / 数字员工（专家）/ 专家团 / 工作流（对接预留）。 */
export type EmployeeKind = "agent" | "expert" | "team" | "workflow";

/** 可见范围：全员共享 / 部门专属 / 仅创建者。 */
export type EmployeeVisibility = "org" | "department" | "private";

/**
 * 可配置范围（后台配置域授权维）：仅创建者可配 / 部门可配。
 * 不支持 org——「全员可配」用 team_lead 角色表达，避免误配。
 */
export type ManageVisibility = "private" | "department";

/** 专家团成员（名称与形象来自 experts 权威源）。 */
export interface TeamMemberItem {
  expert_id: string;
  name: string;
  icon: string;
  role_hint: string;
  member_role: string;
}

/** 注册表行（后端 DigitalEmployeeVO 的同构镜像，禁止本地造字段语义）。 */
export interface DigitalEmployee {
  agent_id: string;
  entity_kind: EmployeeKind;
  entity_id: string;
  name: string;
  title: string;
  description: string;
  icon: string;
  enabled: boolean;
  pinned: boolean;
  startup_status: string;
  lifecycle_status: string;
  /** 专家团编排模式：router-智能调度 / pipeline-顺序流水线，非团为空。 */
  mode: string;
  backend: string;
  model_label: string;
  department_id: string | null;
  department_name: string;
  visibility: EmployeeVisibility;
  /** 是否已有治理行：未治理行的 visibility 只是默认语义，不参与徽标展示。 */
  governed: boolean;
  granted_departments: string[];
  granted_department_names: string[];
  member_count: number;
  members: TeamMemberItem[];
  usage_count: number;
  is_builtin: boolean;
  tags: string[];
  workspace_dir: string;
  available_in_chat: boolean;
  managed_by_app: string | null;
  backend_capabilities: Record<string, unknown>;
  owner_id: string | null;
  usable: boolean;
  /**
   * 后台配置域判定：当前 viewer 是否可配置该员工（S1 写权限）。
   * 后端注册表按 viewer 一次快照批量判定（manage grants + 角色 + owner 兜底），
   * 前端据此过滤工作台管理型 Tab、只读化 ModelSelector，禁止本地复刻判定逻辑。
   */
  manageable: boolean;
  /** 可配置范围（管理授权维）：private-仅创建者 / department-部门可配。 */
  manage_visibility: ManageVisibility;
  /** 管理授权部门集合（department 可配范围时生效）。 */
  manage_granted_departments: string[];
  /** 管理授权部门名称（与 manage_granted_departments 同序，展示用）。 */
  manage_granted_department_names: string[];
  /** 管理授权用户集合（跨部门显式授权兜底）。 */
  manage_granted_users: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

/** 治理写入载荷：字段缺省（undefined）= 该维度不修改。 */
export interface GovernancePayload {
  /** 归属部门 id；空串表示清空归属，缺省表示不修改。 */
  department_id?: string | null;
  visibility?: EmployeeVisibility;
  /** 授权部门集合；传数组（含空数组）整体替换，缺省不修改。 */
  granted_departments?: string[];
  /** 可配置范围（管理授权维）；缺省不修改。 */
  manage_visibility?: ManageVisibility;
  /** 管理授权部门集合；传数组（含空数组）整体替换，缺省不修改。 */
  manage_granted_departments?: string[];
  /** 管理授权用户集合；传数组（含空数组）整体替换，缺省不修改。 */
  manage_granted_users?: string[];
}

/** 注册表读取筛选参数（与后端 query 一一对应）。 */
export interface RegistryFilters {
  /** all | agents（单体形态）| agent | expert | team | workflow。 */
  kind?: string;
  department_id?: string;
  visibility?: string;
  status?: string;
  q?: string;
  /** true = 只要未归属部门的员工（指标卡「待归属」）。 */
  unassigned?: boolean;
}

const enc = encodeURIComponent;

function queryOf(filters: RegistryFilters | undefined): string {
  if (!filters) {
    return "";
  }
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, String(value));
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const employeeRegistryApi = {
  /** 注册表列表（不传筛选即全量，前端做即时快筛）。 */
  list: (filters?: RegistryFilters) =>
    request<DigitalEmployee[]>(`/agents/registry${queryOf(filters)}`),

  /** 设置单个员工的归属部门与可见范围。 */
  setGovernance: (agentId: string, body: GovernancePayload) =>
    request<DigitalEmployee>(
      `/agents/registry/${enc(agentId)}/governance`,
      { method: "PUT", body: JSON.stringify(body) },
    ),

  /** 批量治理多个员工（表格视图批量操作）。 */
  batchGovernance: (body: GovernancePayload & { agent_ids: string[] }) =>
    request<DigitalEmployee[]>("/agents/registry/governance/batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
