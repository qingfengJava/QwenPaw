/**
 * TeamWorkbenchDetail 渲染测试：五 Tab 条、概览（组织架构/协作机制/
 * 团队建设）、协作流程（波次预览）、运维（运行记录）与 404/403 降级。
 * API 层整体 mock（不触网）；模式说明经 metadata 注入（单一来源）。
 */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { createElement, lazy, useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

// 测试环境无 I18nextProvider：真实初始化 i18n 并强制中文，
// 使 t(key, fallback, options) 的插值与 zh.json 资源生效。
import i18nInstance from "../../../../i18n";
import type { TeamTabKey } from "./teamTabs";

beforeAll(() => {
  void i18nInstance.changeLanguage("zh");
});

const getTeam = vi.fn();
const metadata = vi.fn();
const versions = vi.fn();
const capabilities = vi.fn();
const memberUpdates = vi.fn();
const listRuns = vi.fn();

vi.mock("../../../../api/modules/admin", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../../../api/modules/admin")>();
  return {
    ...actual,
    adminExpertTeamsApi: {
      ...actual.adminExpertTeamsApi,
      get: (...args: unknown[]) => getTeam(...args),
      metadata: () => metadata(),
      versions: (...args: unknown[]) => versions(...args),
      capabilities: (...args: unknown[]) => capabilities(...args),
      memberUpdates: (...args: unknown[]) => memberUpdates(...args),
    },
  };
});

// 概览统计与运维 Tab 直接从 workforce 子模块导入：同路径 mock 覆盖。
vi.mock("../../../../api/modules/admin/workforce", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("../../../../api/modules/admin/workforce")
    >();
  return {
    ...actual,
    adminWorkforceApi: {
      ...actual.adminWorkforceApi,
      listRuns: (...args: unknown[]) => listRuns(...args),
      testRun: (...args: unknown[]) => testRun(...args),
    },
  };
});

// 懒加载 RunLogDetailPage：测试环境 mock 为简单占位组件，避免依赖 Vite glob map。
/* eslint-disable @typescript-eslint/no-explicit-any */
vi.mock("@/utils/lazyWithRetry", () => ({
  lazyImportWithRetry: () =>
    lazy(() =>
      Promise.resolve({
        default: () => createElement("div", null, "MockRunLogDetail"),
      }),
    ),
  lazyWithRetry: (factory: () => Promise<any>) =>
    lazy(() => factory().then((m: any) => ({ default: m.default }))),
}));
/* eslint-enable @typescript-eslint/no-explicit-any */

import TeamWorkbenchDetail from "./TeamWorkbenchDetail";

const TEAM = {
  id: "team-1",
  name: "研发交付团队",
  description: "端到端交付",
  mode: "router",
  router_prompt: "",
  status: "published",
  version: 3,
  orchestration: {
    runtime_enabled: true,
    nodes: [{ node_key: "node-1", deps: [] }],
    fast_nodes: [{ node_key: "fast-1", deps: [] }],
    policy: {
      max_repair_per_node: 3,
      max_replan: 2,
      max_total_seconds: 3600,
      max_total_tokens: 0,
      parallelism: 2,
    },
    plan_note: "先澄清后执行",
  },
  sample_tasks: [{ title: "撰写需求文档", prompt: "写一份登录模块需求" }],
  showcase: [{ title: "年度交付报告", desc: "汇总全年交付" }],
  members: [],
};

const META = {
  member_roles: [
    { value: "lead", label: "主理人（Leader）" },
    { value: "member", label: "成员" },
  ],
  team_modes: [
    {
      value: "router",
      label: "router",
      description: "主理人接收需求后判断最匹配的成员专家并派发任务。",
    },
  ],
  limits: {
    default_max_repair_per_node: 3,
    default_max_replan: 2,
    default_parallelism: 2,
    default_max_total_seconds: 3600,
    default_max_total_tokens: 0,
  },
  default_runtime_enabled: true,
};

const CAPS = {
  team_id: "team-1",
  members: [
    {
      expert_id: "e1",
      name: "交付总监",
      title: "总监",
      member_role: "lead",
      role_hint: "统筹交付",
      published: true,
      skills: [{ id: "s1" }],
      tools: ["Websearch"],
      kb_ids: ["kb1"],
      sops: [],
      unavailable_reason: "",
    },
    {
      expert_id: "e2",
      name: "开发工程师",
      title: "工程师",
      member_role: "member",
      role_hint: "写代码",
      published: false,
      skills: [],
      tools: [],
      kb_ids: [],
      sops: [],
      unavailable_reason: "草稿状态，发布后可执行",
    },
  ],
};

const RUNS = [
  {
    id: "run-1",
    team_id: "team-1",
    project_id: null,
    source_chat_id: null,
    initiator_id: "qingfeng",
    status: "done",
    goal: "交付登录模块",
    repair_count: 0,
    replan_count: 0,
    escalation_reason: null,
    error: null,
    created_at: "2026-09-22T09:00:00",
    updated_at: "2026-09-22T09:30:00",
  },
  {
    id: "run-2",
    team_id: "team-1",
    project_id: null,
    source_chat_id: null,
    initiator_id: "qingfeng",
    status: "failed",
    goal: "失败任务",
    repair_count: 1,
    replan_count: 2,
    escalation_reason: null,
    error: "budget exceeded",
    created_at: "2026-09-22T10:00:00",
    updated_at: "2026-09-22T10:10:00",
  },
];

function mockHappyPath() {
  getTeam.mockResolvedValue(TEAM);
  metadata.mockResolvedValue(META);
  versions.mockResolvedValue([
    {
      team_id: "team-1",
      version: 3,
      published_by: "qingfeng",
      published_at: "2026-09-21T10:00:00",
    },
  ]);
  capabilities.mockResolvedValue(CAPS);
  memberUpdates.mockResolvedValue([]);
  listRuns.mockResolvedValue(RUNS);
}

const testRun = vi.fn();

function renderDetail(
  initialTab = "overview",
  opts?: { runId?: string | null; onNavigate?: (path: string) => void },
) {
  // Tab 受控于外壳路径解析：测试用带状态的壳模拟外壳的受控行为，
  // 点击 Tab 才能真实切换内容区。
  function Harness() {
    const [tab, setTab] = useState(initialTab as TeamTabKey);
    return (
      <TeamWorkbenchDetail
        aid="team_team-1"
        teamId="team-1"
        canManage
        tab={tab}
        onTabChange={setTab}
        sessionsSlot={null}
        runId={opts?.runId}
        onNavigate={opts?.onNavigate}
      />
    );
  }
  return renderWithProviders(<Harness />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TeamWorkbenchDetail", () => {
  it("概览：五 Tab 齐备，组织架构含主理人/成员卡且未发布标红", async () => {
    mockHappyPath();
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    // 组织视角五 Tab（与员工详情的档案/能力/动态明确区分）
    expect(screen.getByText("概览")).toBeInTheDocument();
    expect(screen.getByText("成员与职责")).toBeInTheDocument();
    expect(screen.getByText("协作流程")).toBeInTheDocument();
    expect(screen.getByText("会话")).toBeInTheDocument();
    expect(screen.getByText("运维")).toBeInTheDocument();
    // 层级组织架构：主理人卡 + 成员卡 + 不可执行原因
    expect(screen.getByText("交付总监")).toBeInTheDocument();
    expect(screen.getByText("主理人")).toBeInTheDocument();
    expect(screen.getByText("开发工程师")).toBeInTheDocument();
    expect(
      screen.getByText("不可执行：草稿状态，发布后可执行"),
    ).toBeInTheDocument();
    // 协作机制说明来自 metadata（单一来源），编排意图来自 plan_note
    expect(
      screen.getByText("主理人接收需求后判断最匹配的成员专家并派发任务。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/先澄清后执行/)).toBeInTheDocument();
    // 团队建设：任务模板 chip + 使用案例 + 版本快照
    expect(screen.getByText("撰写需求文档")).toBeInTheDocument();
    expect(screen.getByText("年度交付报告")).toBeInTheDocument();
    expect(screen.getByText("qingfeng")).toBeInTheDocument();
  });

  it("协作流程 Tab：渲染标准链波次预览与运行边界", async () => {
    mockHappyPath();
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("协作流程"));
    await waitFor(() => {
      expect(screen.getByText("标准链")).toBeInTheDocument();
    });
    // DAG 节点模板以波次预览呈现（模板优先的派发依据）
    expect(screen.getByText("node-1")).toBeInTheDocument();
    // RunPolicy 边界以中文字段名展示（i18n 键与配置侧共用）
    expect(screen.getByText("单节点最大返工")).toBeInTheDocument();
    expect(screen.getByText("token 预算（0=不限）")).toBeInTheDocument();
  });

  it("运维 Tab：渲染团队运行记录（状态/目标/返工次数）", async () => {
    mockHappyPath();
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("运维"));
    await waitFor(() => {
      expect(screen.getByText("交付登录模块")).toBeInTheDocument();
    });
    expect(screen.getByText("失败任务")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });

  it("团队不存在（404）时渲染降级提示", async () => {
    getTeam.mockRejectedValue(
      Object.assign(new Error("not found"), { status: 404 }),
    );
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText(/团队不存在或已删除/)).toBeInTheDocument();
    });
  });

  it("无配置权限（403）时渲染警告降级", async () => {
    getTeam.mockRejectedValue(
      Object.assign(new Error("forbidden"), { status: 403 }),
    );
    renderDetail();
    await waitFor(() => {
      expect(screen.getByText(/无团队配置查看权限/)).toBeInTheDocument();
    });
  });

  it("运维 Tab：点击行触发 onNavigate 跳转运行详情", async () => {
    mockHappyPath();
    const onNavigate = vi.fn();
    renderDetail("ops", { onNavigate });

    await waitFor(() => {
      expect(screen.getByText("交付登录模块")).toBeInTheDocument();
    });
    // antd Table 渲染 <tr role="row">，第一行是表头，第二行是第一条数据。
    const rows = screen.getAllByRole("row");
    fireEvent.click(rows[1]);
    expect(onNavigate).toHaveBeenCalledWith(
      "/studio/team_team-1/sessions/runs/run-1",
    );
  });

  it("runId 存在时渲染 RunLogDetailPage 而非 Tab 内容", async () => {
    mockHappyPath();
    renderDetail("overview", { runId: "run-123" });
    await waitFor(() => {
      expect(screen.getByText("MockRunLogDetail")).toBeInTheDocument();
    });
    // runId 下钻优先于 Tab 内容：概览标题不应出现。
    expect(screen.queryByText("研发交付团队")).not.toBeInTheDocument();
  });

  it("概览：统计加载中显示 … 而非 0", async () => {
    // 团队数据正常加载，仅 listRuns 保持 pending 以观察统计加载态。
    mockHappyPath();
    listRuns.mockReturnValue(new Promise(() => {}));
    renderDetail();
    // 等待团队数据渲染出概览（此时 runs 仍在加载）。
    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    // 加载中统计卡应显示 "…"（runsLoading=true 时 3 个运行统计均为 "…"）。
    expect(screen.getAllByText("…")).toHaveLength(3);
  });

  it("概览：任务模板执行成功显示回执", async () => {
    mockHappyPath();
    testRun.mockResolvedValue({ id: "run-new" });
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("撰写需求文档")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("撰写需求文档"));
    await waitFor(() => {
      expect(screen.getByText("已发起试运行")).toBeInTheDocument();
    });
  });

  it("概览：任务模板执行失败显示错误回执", async () => {
    mockHappyPath();
    testRun.mockRejectedValue(new Error("network error"));
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("撰写需求文档")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("撰写需求文档"));
    await waitFor(() => {
      expect(screen.getByText("试运行发起失败")).toBeInTheDocument();
    });
  });

  it("概览：运行统计加载失败显示警告提示", async () => {
    mockHappyPath();
    listRuns.mockRejectedValue(new Error("server error"));
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByText("运行统计加载失败，上方数据可能不准确"),
      ).toBeInTheDocument();
    });
  });

  it("概览：成员升级提醒显示可升级成员列表", async () => {
    mockHappyPath();
    memberUpdates.mockResolvedValue([
      {
        expert_id: "e1",
        expert_name: "交付总监",
        bound_version: 1,
        latest_version: 3,
        upgradable: true,
      },
      {
        expert_id: "e2",
        expert_name: "开发工程师",
        bound_version: 2,
        latest_version: 2,
        upgradable: false,
      },
    ]);
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText(/1 位成员有新版本可升级/)).toBeInTheDocument();
    });
    // 仅可升级成员显示（升级提醒 + 组织图均含“交付总监”，用 getAllBy）
    expect(screen.getAllByText(/交付总监/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/v1 → v3/)).toBeInTheDocument();
  });

  it("概览：能力投影加载失败显示警告而非空组织图", async () => {
    mockHappyPath();
    capabilities.mockRejectedValue(new Error("server error"));
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByText(/能力投影加载失败/),
      ).toBeInTheDocument();
    });
  });

  it("概览：版本记录加载失败显示警告而非空表格", async () => {
    mockHappyPath();
    versions.mockRejectedValue(new Error("server error"));
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("版本记录加载失败")).toBeInTheDocument();
    });
  });

  it("概览：收到 team-config-changed 事件后重新拉取数据", async () => {
    mockHappyPath();
    renderDetail();

    // 等待初始加载完成
    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });

    // 记录初始调用次数
    const initialGetTeamCalls = getTeam.mock.calls.length;

    // 派发配置变更事件（匹配当前 teamId）
    act(() => {
      window.dispatchEvent(
        new CustomEvent("qwenpaw:team-config-changed", {
          detail: { teamId: "team-1" },
        }),
      );
    });

    // 等待重新拉取
    await waitFor(() => {
      expect(getTeam.mock.calls.length).toBeGreaterThan(initialGetTeamCalls);
    });
  });

  it("概览：team-config-changed 事件 teamId 不匹配时不触发刷新", async () => {
    mockHappyPath();
    renderDetail();

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });

    const initialGetTeamCalls = getTeam.mock.calls.length;

    // 派发不匹配 teamId 的事件
    act(() => {
      window.dispatchEvent(
        new CustomEvent("qwenpaw:team-config-changed", {
          detail: { teamId: "other-team" },
        }),
      );
    });

    // 等待一段时间确认不会触发额外请求
    await new Promise((r) => setTimeout(r, 100));
    expect(getTeam.mock.calls.length).toBe(initialGetTeamCalls);
  });
});
