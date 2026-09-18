import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import type {
  DigitalEmployee,
  EmployeeKind,
} from "@/api/modules/employeeRegistry";
import type { DepartmentTree } from "@/api/modules/admin";
import { EmployeeKindCard } from "./EmployeeKindCard";
import { GovernanceModal } from "./GovernanceModal";
import { GovernanceTable } from "./GovernanceTable";
import { TeamKindCard } from "./TeamKindCard";
import { WorkflowEmptyState } from "./WorkflowEmptyState";

// Enum copy comes from i18n only: asserting the key proves the component
// never hardcodes a label or builds its own lookup table.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh" },
  }),
}));

// 治理弹窗打开时会拉取管理授权用户候选（/admin/users）；测试中 mock
// 为空列表，避免真实 fetch 与 act 警告（用户维度不影响本组断言）。
vi.mock("@/api/modules/admin/users", () => ({
  adminUsersApi: { list: vi.fn().mockResolvedValue([]) },
}));

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
    title: "Solution architect",
    description: "handles renewals",
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

function department(id: string, name: string): DepartmentTree {
  return {
    id,
    parent_id: null,
    name,
    path: name.toLowerCase(),
    description: "",
    children: [],
  };
}

/**
 * Badges concatenate code copy ("department · Sales"), and antd duplicates
 * header cells for its measure row, so text lookups need containment. The
 * leaf check keeps ancestors (same textContent) from matching too.
 */
const contains =
  (needle: string) =>
  (_content: string, element: Element | null): boolean =>
    !!element &&
    element.children.length === 0 &&
    (element.textContent ?? "").includes(needle);

const DEPARTMENTS = [department("d_sales", "Sales"), department("d_support", "Support")];

describe("EmployeeKindCard", () => {
  it("shows kind, owning department and visibility once governed", () => {
    renderWithProviders(
      <EmployeeKindCard
        employee={employee("expert_sales", "expert", {
          entity_id: "sales",
          department_id: "d_sales",
          department_name: "Sales",
          visibility: "department",
          governed: true,
        })}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("employee.kind.expert")).toBeInTheDocument();
    expect(screen.getByText(contains("employee.visibility.department"))).toBeInTheDocument();
    expect(screen.getByText("expert_sales")).toBeInTheDocument();
    expect(screen.getByText("Solution architect")).toBeInTheDocument();
  });

  it("hides the visibility badge for ungoverned employees", () => {
    renderWithProviders(
      <EmployeeKindCard employee={employee("default", "agent")} onOpen={vi.fn()} />,
    );

    expect(screen.getByText("employee.kind.agent")).toBeInTheDocument();
    // The default org value is not a human decision: no badge, no placeholder.
    expect(screen.queryByText(contains("employee.visibility"))).not.toBeInTheDocument();
  });

  it("opens through the single workbench entry point on click and keyboard", () => {
    const onOpen = vi.fn();
    renderWithProviders(
      <EmployeeKindCard employee={employee("default", "agent")} onOpen={onOpen} />,
    );

    const card = screen.getByRole("button", { name: "default" });
    fireEvent.click(card);
    fireEvent.keyDown(card, { key: "Enter" });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});

describe("TeamKindCard", () => {
  it("renders the member stack, member count and orchestration mode", () => {
    const members = Array.from({ length: 6 }).map((_, index) => ({
      expert_id: `m${index}`,
      name: `Member${index}`,
      icon: "",
      role_hint: "",
      member_role: "member",
    }));
    const { container } = renderWithProviders(
      <TeamKindCard
        employee={employee("team_support", "team", {
          entity_id: "support",
          mode: "pipeline",
          member_count: members.length,
          members,
        })}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("employee.kind.team")).toBeInTheDocument();
    expect(screen.getByText("employee.teamMode.pipeline")).toBeInTheDocument();
    expect(screen.getByText("employee.team.memberCount")).toBeInTheDocument();
    // Stack is capped at four avatars plus one overflow chip.
    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(
      container.querySelectorAll('[class*="memberChip"]'),
    ).toHaveLength(4);
  });
});

describe("WorkflowEmptyState", () => {
  it("explains the reserved category without inventing rows", () => {
    const { container } = renderWithProviders(<WorkflowEmptyState />);

    expect(screen.getByText("employee.workflow.emptyTitle")).toBeInTheDocument();
    expect(container.querySelectorAll("table")).toHaveLength(0);
  });
});

describe("GovernanceTable", () => {
  const rows = [
    employee("default", "agent"),
    employee("expert_sales", "expert", {
      entity_id: "sales",
      department_id: "d_sales",
      department_name: "Sales",
      visibility: "department",
      governed: true,
      granted_department_names: ["Support"],
    }),
    employee("team_support", "team", {
      entity_id: "support",
      member_count: 3,
      mode: "router",
    }),
  ];

  it("renders governance columns and selects rows for batch actions", async () => {
    const onSelectionChange = vi.fn();
    renderWithProviders(
      <GovernanceTable
        rows={rows}
        loading={false}
        canGovern
        selectedIds={[]}
        onSelectionChange={onSelectionChange}
        onOpen={vi.fn()}
        onGovernance={vi.fn()}
      />,
    );

    expect(
      screen.getAllByText("employee.table.colDepartment").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("employee.table.colVisibility").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("employee.table.colShared").length,
    ).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    await waitFor(() =>
      expect(onSelectionChange).toHaveBeenCalledWith(["default"]),
    );
  });

  it("leaves the visibility cell empty until a row is governed", () => {
    renderWithProviders(
      <GovernanceTable
        rows={rows}
        loading={false}
        canGovern={false}
        selectedIds={[]}
        onSelectionChange={vi.fn()}
        onOpen={vi.fn()}
        onGovernance={vi.fn()}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // Only the governed row exposes a visibility decision.
    expect(
      screen.getAllByText(contains("employee.visibility.department")),
    ).toHaveLength(1);
    // Read-only viewers get no governance affordances at all.
    expect(screen.queryAllByLabelText("employee.action.governance")).toHaveLength(
      0,
    );
  });
});

describe("GovernanceModal", () => {
  it("submits the cleared department when nothing was governed", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <GovernanceModal
        open
        targets={[employee("default", "agent")]}
        departments={DEPARTMENTS}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        department_id: "",
        visibility: "org",
        granted_departments: [],
        manage_visibility: "private",
        manage_granted_departments: [],
        manage_granted_users: [],
      }),
    );
  });

  it("refuses department scope until a department is in play", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <GovernanceModal
        open
        targets={[employee("default", "agent")]}
        departments={DEPARTMENTS}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByText("employee.visibility.department"));

    // waitFor 同时刷新弹窗打开时拉取管理授权用户的异步 setState（包在 act 内）
    await waitFor(() =>
      expect(
        screen.getByText("employee.governance.needDepartment"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("common.save").closest("button")).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("resets mixed-value dimensions instead of copying the first target", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <GovernanceModal
        open
        targets={[
          employee("expert_sales", "expert", {
            entity_id: "sales",
            department_id: "d_sales",
            department_name: "Sales",
            visibility: "department",
            governed: true,
            granted_departments: ["d_support"],
            granted_department_names: ["Support"],
          }),
          employee("team_support", "team", { entity_id: "support" }),
        ]}
        departments={DEPARTMENTS}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    // Batch mode lists every target so the operator sees the blast radius.
    expect(screen.getByText("expert_sales")).toBeInTheDocument();
    expect(screen.getByText("team_support")).toBeInTheDocument();

    // The two targets disagree on every dimension: the modal must NOT
    // prefill the first target's values (they would silently overwrite
    // the whole batch); unset dimensions fall back to safe defaults.
    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        department_id: "",
        visibility: "org",
        granted_departments: [],
        manage_visibility: "private",
        manage_granted_departments: [],
        manage_granted_users: [],
      }),
    );
  });

  it("keeps shared values prefilled for a uniform batch write", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const shared = {
      department_id: "d_sales",
      department_name: "Sales",
      visibility: "department" as const,
      governed: true,
      granted_departments: ["d_support"],
      granted_department_names: ["Support"],
    };
    renderWithProviders(
      <GovernanceModal
        open
        targets={[
          employee("expert_sales", "expert", {
            entity_id: "sales",
            ...shared,
          }),
          employee("expert_sales2", "expert", {
            entity_id: "sales2",
            ...shared,
          }),
        ]}
        departments={DEPARTMENTS}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByText("common.save"));

    // Uniform batch: shared values are kept so the operator sees the
    // current state instead of a blank form.
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        department_id: "d_sales",
        visibility: "department",
        granted_departments: ["d_support"],
        manage_visibility: "private",
        manage_granted_departments: [],
        manage_granted_users: [],
      }),
    );
  });
});
