// @vitest-environment jsdom
/**
 * TeamDetailModal 渲染测试：「任务示例」模板行（点击回调携带 prompt
 * 作为 goal）、「使用案例」静态卡与「最近交付」真实投影（done run
 * 前 2 条 + 徽标）双轨并存；workforceApi.list 打桩。
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TeamDetailModal from "./TeamDetailModal";
import type { ExpertTeam, TeamRun } from "../../api/modules";

vi.mock("../../api/modules", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../api/modules")>();
  return {
    ...actual,
    workforceApi: {
      ...actual.workforceApi,
      list: vi.fn(),
    },
  };
});

import { workforceApi } from "../../api/modules";

afterEach(cleanup);

function makeTeam(overrides: Partial<ExpertTeam> = {}): ExpertTeam {
  return {
    id: "team_sw",
    name: "软件开发团队",
    description: "高效软件研发团队",
    mode: "router",
    version: 1,
    agent_id: "team_team_sw",
    member_count: 5,
    members: [
      {
        expert_id: "builtin_dir_deliver",
        name: "成必达",
        title: "交付总监",
        icon: "fa-solid fa-flag-checkered",
        role_hint: "中央大脑",
        member_role: "lead",
      },
      {
        expert_id: "builtin_pm_needs",
        name: "需明白",
        title: "产品经理",
        icon: "fa-solid fa-clipboard-list",
        role_hint: "需求分析",
        member_role: "member",
      },
    ],
    sample_tasks: [
      {
        title: "帮我开发一个贪吃蛇游戏",
        prompt: "帮我开发一个贪吃蛇游戏，要求可以网页打开直接玩。",
      },
    ],
    showcase: [
      {
        title: "单词记忆 App 从需求到交付",
        desc: "五节点标准链全流程。",
        tags: ["标准链"],
      },
    ],
    ...overrides,
  };
}

function makeRun(overrides: Partial<TeamRun> = {}): TeamRun {
  return {
    id: "run_1",
    team_id: "team_sw",
    project_id: null,
    source_chat_id: null,
    initiator_id: "alice",
    status: "done",
    goal: "开发一个登录页",
    plan: {},
    policy: {},
    context_version: 1,
    summary: "登录页已交付，含响应式适配",
    result: {},
    clarification: {},
    repair_count: 0,
    replan_count: 0,
    error: "",
    escalation_reason: "",
    updated_at: "2026-08-18T10:00:00Z",
    ...overrides,
  };
}

describe("TeamDetailModal 运营位与交付投影", () => {
  it("渲染任务示例行、静态案例卡与「最近交付」投影（带徽标）", async () => {
    vi.mocked(workforceApi.list).mockResolvedValue([makeRun()]);
    render(
      <TeamDetailModal team={makeTeam()} onClose={() => undefined} onSummon={() => undefined} />,
    );

    expect(await screen.findByText("任务示例")).toBeTruthy();
    expect(screen.getByText("帮我开发一个贪吃蛇游戏")).toBeTruthy();
    expect(screen.getByText("使用案例")).toBeTruthy();
    expect(screen.getByText("单词记忆 App 从需求到交付")).toBeTruthy();
    // 真实交付投影：goal + summary + 徽标
    expect(screen.getByText("开发一个登录页")).toBeTruthy();
    expect(screen.getByText(/登录页已交付/)).toBeTruthy();
    expect(screen.getByText("最近交付")).toBeTruthy();
    // workforceApi 以 team_id + status=done 查询
    expect(workforceApi.list).toHaveBeenCalledWith({
      team_id: "team_sw",
      status: "done",
    });
  });

  it("交付投影只取前 2 条", async () => {
    vi.mocked(workforceApi.list).mockResolvedValue([
      makeRun({ id: "run_1", goal: "交付一" }),
      makeRun({ id: "run_2", goal: "交付二" }),
      makeRun({ id: "run_3", goal: "交付三" }),
    ]);
    render(
      <TeamDetailModal team={makeTeam()} onClose={() => undefined} onSummon={() => undefined} />,
    );

    expect(await screen.findByText("交付一")).toBeTruthy();
    expect(screen.getByText("交付二")).toBeTruthy();
    expect(screen.queryByText("交付三")).toBeNull();
  });

  it("无 done run 且有静态案例 → 空态提示文案", async () => {
    vi.mocked(workforceApi.list).mockResolvedValue([]);
    render(
      <TeamDetailModal team={makeTeam()} onClose={() => undefined} onSummon={() => undefined} />,
    );

    await waitFor(() =>
      expect(screen.getByText("单词记忆 App 从需求到交付")).toBeTruthy(),
    );
    expect(screen.getByText(/该团队暂无已完成任务/)).toBeTruthy();
  });

  it("点击任务示例行 → onSummon 携带 (team, prompt)", async () => {
    vi.mocked(workforceApi.list).mockResolvedValue([]);
    const onSummon = vi.fn();
    render(
      <TeamDetailModal team={makeTeam()} onClose={() => undefined} onSummon={onSummon} />,
    );

    fireEvent.click(await screen.findByText("帮我开发一个贪吃蛇游戏"));
    expect(onSummon).toHaveBeenCalledTimes(1);
    const [team, kickoff] = onSummon.mock.calls[0];
    expect(team.id).toBe("team_sw");
    expect(kickoff).toBe("帮我开发一个贪吃蛇游戏，要求可以网页打开直接玩。");
  });
});
