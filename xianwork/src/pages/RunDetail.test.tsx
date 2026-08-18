// @vitest-environment jsdom
/**
 * RunDetail 渲染测试：DAG 波次/节点时间线（契约-结果-返工）与
 * 干预按钮状态机（取消/续跑/放行重试/终止/澄清提交）按 run.status
 * 正确显隐。API 与 SSE 订阅全部打桩——本测试只关心纯渲染语义。
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import RunDetailPage from "./RunDetail";
import { ToastProvider } from "../components/Toast";
import { useTeamRunsStore } from "../stores/teamRuns";
import type { TeamRun, TeamRunNode } from "../api/modules";

// SSE 订阅打桩（页面挂载即订阅，测试中静默关闭）
vi.mock("../lib/feedStream", () => ({
  subscribeRunEvents: () => ({ close: () => undefined }),
}));

afterEach(cleanup);

beforeEach(() => {
  useTeamRunsStore.setState({ detail: null, detailLoading: false });
  useTeamRunsStore.getState().clearDetail();
});

function nodeRow(overrides: Partial<TeamRunNode> = {}): TeamRunNode {
  return {
    run_id: "run_1",
    node_key: "task-1",
    assignee_expert_id: "exp_1",
    assignee_user_id: null,
    node_type: "task",
    status: "done",
    contract: { objective: "产出前端方案", expected_output: ["结构化方案"] },
    result: { result_text: "方案正文 ABC", result: {} },
    repair: {},
    verdict: "PASS",
    repair_count: 0,
    session_id: "s1",
    token_cost: 1200,
    attempt: 1,
    ...overrides,
  };
}

function makeRun(overrides: Partial<TeamRun> = {}): TeamRun {
  return {
    id: "run_1",
    team_id: "team_tech",
    project_id: null,
    source_chat_id: null,
    initiator_id: "alice",
    status: "done",
    goal: "设计一个登录页",
    plan: {
      nodes: [
        { node_key: "task-1", deps: [], node_type: "task", objective: "产出前端方案" },
        { node_key: "final-summary", deps: ["task-1"], node_type: "final", objective: "汇总" },
      ],
    },
    policy: {},
    context_version: 1,
    summary: "最终交付：登录页方案已完成",
    result: {},
    clarification: {},
    repair_count: 0,
    replan_count: 0,
    error: "",
    escalation_reason: "",
    nodes: [
      nodeRow(),
      nodeRow({
        node_key: "final-summary",
        node_type: "final",
        contract: { objective: "汇总" },
        result: { result_text: "最终交付：登录页方案已完成" },
        assignee_expert_id: "",
      }),
    ],
    ...overrides,
  };
}

function renderPage(run: TeamRun | null) {
  useTeamRunsStore.setState({ detail: run, detailLoading: false });
  return render(
    <ToastProvider>
      <MemoryRouter>
        <RunDetailPage />
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("RunDetail 状态机渲染", () => {
  it("done：最终交付卡 + 两波 DAG 分层 + 节点状态徽标", () => {
    renderPage(makeRun());
    expect(screen.getByText("最终交付")).toBeTruthy();
    expect(screen.getByText(/登录页方案已完成/)).toBeTruthy();
    // 波次分层：第 1 波单节点（task-1），第 2 波单节点（final）
    expect(screen.getByText("第 1 波（单节点）")).toBeTruthy();
    expect(screen.getByText("第 2 波（单节点）")).toBeTruthy();
    // final 节点显示为中央大脑；成员节点显示 node_key
    expect(screen.getByText("中央大脑")).toBeTruthy();
    expect(screen.getByText("task-1")).toBeTruthy();
    // done 态不显示取消/续跑/人工裁决按钮
    expect(screen.queryByText("取消任务")).toBeNull();
    expect(screen.queryByText("续跑")).toBeNull();
    expect(screen.queryByText("放行重试")).toBeNull();
  });

  it("running：显示取消任务，无人工裁决条", () => {
    renderPage(makeRun({ status: "running", summary: "" }));
    expect(screen.getByText("取消任务")).toBeTruthy();
    expect(screen.queryByText("放行重试")).toBeNull();
    expect(screen.queryByText("最终交付")).toBeNull();
  });

  it("escalated：人工裁决条显示放行重试与终止任务", () => {
    renderPage(
      makeRun({
        status: "escalated",
        escalation_reason: "节点 task-1 连续返工超限",
        nodes: [
          nodeRow({ status: "failed", verdict: "ESCALATE", repair_count: 3 }),
        ],
      }),
    );
    expect(screen.getByText("放行重试")).toBeTruthy();
    expect(screen.getByText("终止任务")).toBeTruthy();
    // 熔断原因同时出现在头部卡与人工裁决条（两处留痕）
    expect(screen.getAllByText(/连续返工超限/).length).toBeGreaterThanOrEqual(1);
    // escalated 非活跃态：无取消按钮
    expect(screen.queryByText("取消任务")).toBeNull();
  });

  it("interrupted：显示续跑入口", () => {
    renderPage(makeRun({ status: "interrupted", summary: "" }));
    expect(screen.getByText("续跑")).toBeTruthy();
  });

  it("awaiting_confirm：澄清问答卡，未作答时提交禁用", () => {
    renderPage(
      makeRun({
        status: "awaiting_confirm",
        summary: "",
        clarification: { questions: ["目标平台是 Web 还是小程序？"] },
      }),
    );
    expect(
      screen.getByText("中央大脑需要你澄清以下问题"),
    ).toBeTruthy();
    expect(
      screen.getByText("目标平台是 Web 还是小程序？"),
    ).toBeTruthy();
    const submit = screen.getByText("提交答复").closest("button")!;
    expect(submit.disabled).toBe(true);
    // 输入答复后解除禁用
    fireEvent.change(screen.getByPlaceholderText("输入你的答复…"), {
      target: { value: "Web 平台" },
    });
    expect(submit.disabled).toBe(false);
  });
});

describe("RunDetail 节点时间线（展开契约-结果-返工）", () => {
  it("点击节点展开：期望产出 / 验收标准 / 返工问题 / 结果正文", () => {
    renderPage(
      makeRun({
        nodes: [
          nodeRow({
            status: "repairing",
            verdict: "FAIL",
            repair_count: 2,
            attempt: 3,
            contract: {
              objective: "产出前端方案",
              expected_output: ["结构化方案"],
              quality_criteria: ["覆盖响应式布局"],
            },
            repair: { issues: ["缺少移动端适配"] },
          }),
        ],
      }),
    );
    // 返工计数徽标
    expect(screen.getByText("返工 2")).toBeTruthy();
    expect(screen.getByText("第 3 轮")).toBeTruthy();
    // 展开
    fireEvent.click(screen.getByText("task-1"));
    expect(screen.getByText(/期望产出：结构化方案/)).toBeTruthy();
    expect(screen.getByText(/验收标准：覆盖响应式布局/)).toBeTruthy();
    expect(screen.getByText(/返工问题：1\. 缺少移动端适配/)).toBeTruthy();
    expect(screen.getByText("方案正文 ABC")).toBeTruthy();
  });

  it("未执行节点：无结果时显示尚未执行", () => {
    renderPage(
      makeRun({
        nodes: [nodeRow({ status: "pending", result: {}, verdict: "" })],
      }),
    );
    fireEvent.click(screen.getByText("task-1"));
    expect(screen.getByText("（尚未执行）")).toBeTruthy();
  });
});
