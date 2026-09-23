import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type {
  DigitalEmployee,
  EmployeeKind,
  EmployeeVisibility,
} from "@/api/modules/employeeRegistry";
import type { DepartmentTree } from "@/api/modules/admin";
import { useEmployeeRegistry } from "./useEmployeeRegistry";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  setGovernance: vi.fn(),
  batchGovernance: vi.fn(),
  departmentTree: vi.fn(),
}));

vi.mock("@/api/modules/employeeRegistry", () => ({
  employeeRegistryApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    setGovernance: (...args: unknown[]) => mocks.setGovernance(...args),
    batchGovernance: (...args: unknown[]) => mocks.batchGovernance(...args),
  },
}));

vi.mock("@/api/modules/admin", () => ({
  adminOrgsApi: {
    departmentTree: (...args: unknown[]) => mocks.departmentTree(...args),
  },
}));

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function employee(
  agentId: string,
  kind: EmployeeKind,
  overrides: Partial<DigitalEmployee> = {},
): DigitalEmployee {
  return {
    agent_id: agentId,
    entity_kind: kind,
    entity_id: agentId,
    name: agentId,
    title: "",
    description: "",
    icon: "",
    enabled: true,
    pinned: false,
    startup_status: "running",
    lifecycle_status: "published",
    mode: "",
    backend: "qwenpaw",
    model_label: "qwen-max",
    department_id: null,
    department_name: "",
    visibility: "org",
    governed: false,
    granted_departments: [],
    granted_department_names: [],
    member_count: 0,
    members: [],
    usage_count: 0,
    is_builtin: false,
    tags: [],
    workspace_dir: `/ws/${agentId}`,
    available_in_chat: true,
    managed_by_app: null,
    backend_capabilities: {},
    owner_id: null,
    usable: true,
    manageable: true,
    manage_visibility: "private",
    manage_granted_departments: [],
    manage_granted_department_names: [],
    manage_granted_users: [],
    ...overrides,
  };
}

function department(
  id: string,
  name: string,
  children: DepartmentTree[] = [],
): DepartmentTree {
  return {
    id,
    parent_id: null,
    name,
    path: name.toLowerCase(),
    description: "",
    children,
  };
}

const ROWS: DigitalEmployee[] = [
  employee("default", "agent"),
  employee("expert_sales", "expert", {
    entity_id: "sales",
    name: "销售助手",
    department_id: "d_sales",
    department_name: "Sales",
    visibility: "department",
    governed: true,
    granted_departments: ["d_support"],
    granted_department_names: ["Support"],
    tags: ["crm"],
  }),
  employee("expert_private", "expert", {
    entity_id: "private",
    name: "个人助理",
    visibility: "private",
    governed: true,
    startup_status: "stopped",
    enabled: false,
  }),
  employee("team_support", "team", {
    entity_id: "support",
    name: "客服团",
    mode: "router",
    member_count: 2,
    members: [
      {
        expert_id: "a",
        name: "A",
        icon: "",
        role_hint: "",
        member_role: "member",
      },
    ],
  }),
];

async function renderLoaded(rows = ROWS) {
  mocks.list.mockResolvedValue(rows);
  mocks.departmentTree.mockResolvedValue([
    department("d_sales", "Sales"),
    department("d_support", "Support"),
  ]);
  const hook = renderHook(() => useEmployeeRegistry());
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  await waitFor(() => expect(hook.result.current.rows).toHaveLength(rows.length));
  return hook;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// loading + derived stats
// ---------------------------------------------------------------------------

it("loads the registry once and derives kind / governance stats", async () => {
  const { result } = await renderLoaded();

  expect(mocks.list).toHaveBeenCalledTimes(1);
  expect(result.current.stats).toEqual({
    total: 4,
    agents: 3,
    teams: 1,
    running: 3,
    departmentScoped: 1,
    unassigned: 3,
  });
});

it("surfaces a load failure without dropping the retry path", async () => {
  mocks.list.mockRejectedValue(new Error("registry unavailable"));
  mocks.departmentTree.mockResolvedValue([]);
  const { result } = renderHook(() => useEmployeeRegistry());

  await waitFor(() => expect(result.current.error).toBeTruthy());
  expect(result.current.rows).toEqual([]);

  mocks.list.mockResolvedValue(ROWS);
  await act(async () => {
    await result.current.reload();
  });
  expect(result.current.error).toBeNull();
  expect(result.current.rows).toHaveLength(4);
});

it("keeps the employee list alive when the department tree fails", async () => {
  mocks.list.mockResolvedValue(ROWS);
  mocks.departmentTree.mockRejectedValue(new Error("orgs down"));
  const { result } = renderHook(() => useEmployeeRegistry());

  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.rows).toHaveLength(4);
  expect(result.current.departments).toEqual([]);
  expect(result.current.error).toBeNull();
});

// ---------------------------------------------------------------------------
// filters
// ---------------------------------------------------------------------------

it("partitions the kind tabs and keeps workflow as an empty placeholder", async () => {
  const { result } = await renderLoaded();

  act(() => result.current.setFilter("tab", "agents"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "default",
    "expert_sales",
    "expert_private",
  ]);

  act(() => result.current.setFilter("tab", "team"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "team_support",
  ]);

  // Workflow has no backing entity this iteration: never fake rows.
  act(() => result.current.setFilter("tab", "workflow"));
  expect(result.current.filtered).toEqual([]);
});

it("narrows the agent tab by second-level kind chips", async () => {
  const { result } = await renderLoaded();

  act(() => result.current.setFilter("tab", "all"));
  act(() => result.current.setFilter("agentKind", "expert"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "expert_sales",
    "expert_private",
  ]);

  act(() => result.current.setFilter("agentKind", "agent"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "default",
  ]);
});

it("filters by department, visibility, lifecycle, keyword and unassigned", async () => {
  const { result } = await renderLoaded();

  act(() => result.current.setFilter("departmentId", "d_sales"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "expert_sales",
  ]);

  act(() => result.current.setFilter("departmentId", ""));
  act(() => result.current.setFilter("visibility", "private"));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "expert_private",
  ]);

  act(() => result.current.setFilter("visibility", ""));
  act(() => result.current.setFilter("lifecycle", "draft"));
  expect(result.current.filtered).toEqual([]);

  act(() => result.current.setFilter("lifecycle", ""));
  act(() => result.current.setFilter("keyword", " CRM "));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "expert_sales",
  ]);

  act(() => result.current.setFilter("keyword", ""));
  act(() => result.current.setFilter("unassignedOnly", true));
  expect(result.current.filtered.map((row) => row.agent_id)).toEqual([
    "default",
    "expert_private",
    "team_support",
  ]);
});

it("resets every filter but the active kind tab", async () => {
  const { result } = await renderLoaded();

  act(() => result.current.setFilter("tab", "agents"));
  act(() => result.current.setFilter("keyword", "sales"));
  act(() => result.current.setFilter("visibility", "org" as EmployeeVisibility));

  act(() => result.current.resetFilters());

  expect(result.current.filters.tab).toBe("agents");
  expect(result.current.filters.keyword).toBe("");
  expect(result.current.filters.visibility).toBe("");
  expect(result.current.filtered).toHaveLength(3);
});

// ---------------------------------------------------------------------------
// governance writes (row-level refresh)
// ---------------------------------------------------------------------------

it("merges only the affected row after a governance save", async () => {
  const { result } = await renderLoaded();
  const updated = employee("expert_sales", "expert", {
    entity_id: "sales",
    department_id: "d_support",
    department_name: "Support",
    visibility: "department",
    governed: true,
  });
  mocks.setGovernance.mockResolvedValue(updated);

  await act(async () => {
    await result.current.saveGovernance("expert_sales", {
      department_id: "d_support",
      visibility: "department",
    });
  });

  expect(mocks.setGovernance).toHaveBeenCalledWith("expert_sales", {
    department_id: "d_support",
    visibility: "department",
  });
  const sales = result.current.rows.find((row) => row.agent_id === "expert_sales");
  expect(sales?.department_name).toBe("Support");
  // Untouched rows keep their identity (no full refetch, no flicker).
  expect(mocks.list).toHaveBeenCalledTimes(1);
  expect(
    result.current.rows.find((row) => row.agent_id === "default"),
  ).toMatchObject({ department_name: "" });
});

it("applies one batch write across every selected row", async () => {
  const { result } = await renderLoaded();
  mocks.batchGovernance.mockResolvedValue([
    employee("default", "agent", {
      department_id: "d_sales",
      department_name: "Sales",
      visibility: "department",
      governed: true,
    }),
    employee("team_support", "team", {
      entity_id: "support",
      mode: "router",
      department_id: "d_sales",
      department_name: "Sales",
      visibility: "department",
      governed: true,
      member_count: 2,
    }),
  ]);

  await act(async () => {
    await result.current.saveBatchGovernance(
      ["default", "team_support"],
      { department_id: "d_sales", visibility: "department" },
    );
  });

  expect(mocks.batchGovernance).toHaveBeenCalledWith({
    agent_ids: ["default", "team_support"],
    department_id: "d_sales",
    visibility: "department",
  });
  expect(
    result.current.rows.filter((row) => row.governed).map((row) => row.agent_id),
    // expert_private keeps its earlier governed state from the fixture.
  ).toEqual(["default", "expert_sales", "expert_private", "team_support"]);
});

// ---------------------------------------------------------------------------
// department grouping
// ---------------------------------------------------------------------------

it("groups by department with the unassigned bucket last", async () => {
  const { result } = await renderLoaded();

  const groups = result.current.groupedByDepartment;
  // Only one owned department in the fixture; the other three rows are
  // unassigned and therefore share one trailing bucket.
  expect(groups.map((group) => group.departmentName)).toEqual(["Sales", ""]);
  expect(groups[groups.length - 1].departmentId).toBe("");
  expect(groups[groups.length - 1].items.map((row) => row.agent_id)).toEqual([
    "default",
    "expert_private",
    "team_support",
  ]);
});
