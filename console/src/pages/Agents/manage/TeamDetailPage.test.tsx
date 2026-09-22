/**
 * TeamDetailPage 渲染测试：概览（名称/版本/版本历史）、成员职责
 * （能力矩阵未发布标红）、Harness 治理 Tab（策略表单）与 404 态。
 * API 层整体 mock（不触网）；枚举/限额经 metadata 注入。
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

const getTeam = vi.fn();
const metadata = vi.fn();
const versions = vi.fn();
const capabilities = vi.fn();
const validate = vi.fn();
const publish = vi.fn();
const update = vi.fn();

vi.mock("../../../api/modules/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/modules/admin")>();
  return {
    ...actual,
    adminExpertTeamsApi: {
      ...actual.adminExpertTeamsApi,
      get: (...args: unknown[]) => getTeam(...args),
      metadata: () => metadata(),
      versions: (...args: unknown[]) => versions(...args),
      capabilities: (...args: unknown[]) => capabilities(...args),
      validate: (...args: unknown[]) => validate(...args),
      publish: (...args: unknown[]) => publish(...args),
      update: (...args: unknown[]) => update(...args),
    },
  };
});

const useParams = vi.fn(() => ({ teamId: "team-1" }));
const navigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => useParams(),
    useNavigate: () => navigate,
  };
});

import TeamDetailPage from "./TeamDetailPage";

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
    fast_nodes: [],
    policy: { max_repair_per_node: 3, max_replan: 2, max_total_seconds: 3600, max_total_tokens: 0, parallelism: 2 },
    plan_note: "",
  },
  members: [],
};

const META = {
  member_roles: [
    { value: "lead", label: "主理人（Leader）" },
    { value: "member", label: "成员" },
  ],
  team_modes: [{ value: "router", label: "router" }],
  limits: {
    default_max_repair_per_node: 3,
    default_max_replan: 2,
    default_parallelism: 2,
    default_max_total_seconds: 3600,
    default_max_total_tokens: 0,
  },
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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TeamDetailPage", () => {
  it("加载后渲染概览（团队名/版本/版本历史）与四个 Tab", async () => {
    getTeam.mockResolvedValue(TEAM);
    metadata.mockResolvedValue(META);
    versions.mockResolvedValue([
      { team_id: "team-1", version: 3, published_by: "qingfeng", published_at: "2026-09-21T10:00:00" },
    ]);
    capabilities.mockResolvedValue(CAPS);

    renderWithProviders(<TeamDetailPage />);

    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    // 四个 Tab 齐备（配置工作台信息架构）
    expect(screen.getByText("概览")).toBeInTheDocument();
    expect(screen.getByText("成员职责")).toBeInTheDocument();
    expect(screen.getByText("协作流程")).toBeInTheDocument();
    expect(screen.getByText("Harness 治理")).toBeInTheDocument();
    // 版本历史展示（审计摘要）
    expect(screen.getByText("qingfeng")).toBeInTheDocument();
  });

  it("成员职责 Tab：未发布成员显式标红并给出原因", async () => {
    getTeam.mockResolvedValue(TEAM);
    metadata.mockResolvedValue(META);
    versions.mockResolvedValue([]);
    capabilities.mockResolvedValue(CAPS);

    renderWithProviders(<TeamDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("研发交付团队")).toBeInTheDocument();
    });
    // antd Tabs 懒渲染：先切到「成员职责」Tab 再断言矩阵内容
    fireEvent.click(screen.getByText("成员职责"));
    await waitFor(() => {
      expect(screen.getByText("交付总监")).toBeInTheDocument();
    });
    expect(screen.getByText("未发布：草稿状态，发布后可执行")).toBeInTheDocument();
    expect(screen.getByText("主理人")).toBeInTheDocument();
  });

  it("团队不存在时渲染 404 提示", async () => {
    getTeam.mockRejectedValue(new Error("404"));
    renderWithProviders(<TeamDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("团队不存在或已删除")).toBeInTheDocument();
    });
  });
});
