/**
 * hooks/useEmployeeRegistry.ts — 数字员工注册表数据源（控制台 + 工作台共用）。
 *
 * 单一来源：列表页与工作台的员工数据、部门归属、可见范围全部来自
 * `GET /agents/registry`，本地不复制任何枚举文案或统计口径。
 *
 * 取全量 + 前端即时快筛：员工量级为数十条，逐字符发请求会让筛选卡顿，
 * 故一次拉全量后在内存过滤（服务端同样支持筛选参数，供 API 侧复用）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  employeeRegistryApi,
  type DigitalEmployee,
  type EmployeeVisibility,
  type GovernancePayload,
} from "@/api/modules/employeeRegistry";
import { adminOrgsApi, type DepartmentTree } from "@/api/modules/admin";
import { invalidateManageable } from "@/hooks/useManageable";

/** 分类 Tab 键：全部 / 智能体（单体形态）/ 专家团 / 工作流（预留）。 */
export type EmployeeTabKey = "all" | "agents" | "team" | "workflow";

/** 智能体 Tab 内的二级形态筛选。 */
export type AgentKindFilter = "all" | "agent" | "expert";

/** 控制台快筛条件（全部为可选，缺省即不筛）。 */
export interface RegistryFilterState {
  tab: EmployeeTabKey;
  agentKind: AgentKindFilter;
  departmentId: string;
  visibility: EmployeeVisibility | "";
  lifecycle: string;
  keyword: string;
  /** 只看未归属（与后端 apply_filters 的 unassigned 同语义）。 */
  unassignedOnly: boolean;
}

export const EMPTY_FILTERS: RegistryFilterState = {
  tab: "all",
  agentKind: "all",
  departmentId: "",
  visibility: "",
  lifecycle: "",
  keyword: "",
  unassignedOnly: false,
};

/** 单行是否命中当前快筛（与后端 apply_filters 同语义）。 */
function matchesFilters(
  row: DigitalEmployee,
  filters: RegistryFilterState,
): boolean {
  if (filters.tab === "agents" && !["agent", "expert"].includes(row.entity_kind)) {
    return false;
  }
  if (filters.tab === "team" && row.entity_kind !== "team") {
    return false;
  }
  // 工作流为外部平台对接预留形态，本期无任何数据源，恒为空集
  if (filters.tab === "workflow") {
    return false;
  }
  if (
    filters.tab === "all" &&
    filters.agentKind !== "all" &&
    row.entity_kind !== filters.agentKind
  ) {
    return false;
  }
  if (filters.departmentId && row.department_id !== filters.departmentId) {
    return false;
  }
  if (filters.unassignedOnly && row.department_id) {
    return false;
  }
  if (filters.visibility && row.visibility !== filters.visibility) {
    return false;
  }
  if (filters.lifecycle && row.lifecycle_status !== filters.lifecycle) {
    return false;
  }
  const keyword = filters.keyword.trim().toLowerCase();
  if (!keyword) {
    return true;
  }
  return `${row.name} ${row.title} ${row.description} ${row.tags.join(" ")}`
    .toLowerCase()
    .includes(keyword);
}

/** 注册表派生统计（指标卡与 Tab 计数的唯一计算入口）。 */
export interface RegistryStats {
  total: number;
  agents: number;
  teams: number;
  running: number;
  departmentScoped: number;
  unassigned: number;
}

function deriveStats(rows: DigitalEmployee[]): RegistryStats {
  return {
    total: rows.length,
    agents: rows.filter((row) => row.entity_kind !== "team").length,
    teams: rows.filter((row) => row.entity_kind === "team").length,
    running: rows.filter((row) => row.startup_status === "running").length,
    departmentScoped: rows.filter(
      (row) => row.visibility === "department",
    ).length,
    unassigned: rows.filter((row) => !row.department_id).length,
  };
}

export function useEmployeeRegistry() {
  const [rows, setRows] = useState<DigitalEmployee[]>([]);
  const [departments, setDepartments] = useState<DepartmentTree[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<RegistryFilterState>(EMPTY_FILTERS);

  const reload = useCallback(async () => {
    setError(null);
    try {
      setRows(await employeeRegistryApi.list());
    } catch (err) {
      console.error("Failed to load employee registry:", err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 部门树独立加载：失败只影响筛选器与治理弹窗，不阻断员工列表
  useEffect(() => {
    let alive = true;
    adminOrgsApi
      .departmentTree()
      .then((tree) => {
        if (alive) setDepartments(tree);
      })
      .catch(() => {
        if (alive) setDepartments([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const patchRows = useCallback(
    (updated: DigitalEmployee[]) => {
      setRows((prev) => {
        const index = new Map(updated.map((row) => [row.agent_id, row]));
        return prev.map((row) => index.get(row.agent_id) ?? row);
      });
    },
    [],
  );

  /** 治理写入：接口回传最新行，仅替换受影响行（不整页重挂）。 */
  const saveGovernance = useCallback(
    async (agentId: string, payload: GovernancePayload) => {
      const updated = await employeeRegistryApi.setGovernance(agentId, payload);
      patchRows([updated]);
      // 管理授权可能已变：失效可管理缓存，桌面端同标签导航的工作台/选择器重取
      invalidateManageable();
      return updated;
    },
    [patchRows],
  );

  /** 批量治理：一次请求写多行，回传后按行合并。 */
  const saveBatchGovernance = useCallback(
    async (agentIds: string[], payload: GovernancePayload) => {
      const updated = await employeeRegistryApi.batchGovernance({
        ...payload,
        agent_ids: agentIds,
      });
      patchRows(updated);
      invalidateManageable();
      return updated;
    },
    [patchRows],
  );

  const filtered = useMemo(
    () => rows.filter((row) => matchesFilters(row, filters)),
    [rows, filters],
  );

  const stats = useMemo(() => deriveStats(rows), [rows]);

  /** 按部门分组（含「未归属」兜底组），组内保持注册表原顺序。 */
  const groupedByDepartment = useMemo(() => {
    const groups = new Map<string, DigitalEmployee[]>();
    filtered.forEach((row) => {
      const key = row.department_id || "";
      const bucket = groups.get(key);
      if (bucket) bucket.push(row);
      else groups.set(key, [row]);
    });
    // 部门顺序跟随部门树先序（组织树语义），未归属固定末位
    const ordered = [...groups.entries()].sort((a, b) => {
      if (!a[0]) return 1;
      if (!b[0]) return -1;
      return a[1][0].department_name.localeCompare(b[1][0].department_name);
    });
    return ordered.map(([departmentId, items]) => ({
      departmentId,
      departmentName: items[0]?.department_name || "",
      items,
    }));
  }, [filtered]);

  const setFilter = useCallback(
    <K extends keyof RegistryFilterState>(key: K, value: RegistryFilterState[K]) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const resetFilters = useCallback(
    () => setFilters((prev) => ({ ...EMPTY_FILTERS, tab: prev.tab })),
    [],
  );

  return {
    rows,
    filtered,
    groupedByDepartment,
    departments,
    stats,
    loading,
    error,
    filters,
    setFilter,
    resetFilters,
    reload,
    saveGovernance,
    saveBatchGovernance,
  };
}
