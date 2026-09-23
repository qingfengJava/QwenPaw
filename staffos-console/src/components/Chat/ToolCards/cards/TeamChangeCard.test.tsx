// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// ── Mocks ──────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

// ToolCardShell 简化为直出 children，便于断言内部内容。
vi.mock("../shared", () => ({
  ToolCardShell: ({
    children,
    title,
    badges,
    defaultExpanded,
  }: {
    children?: React.ReactNode;
    title?: string;
    badges?: React.ReactNode;
    defaultExpanded?: boolean;
  }) => (
    <div data-testid="tool-card-shell" data-expanded={String(Boolean(defaultExpanded))}>
      <span data-testid="shell-title">{title}</span>
      <span data-testid="shell-badges">{badges}</span>
      {children}
    </div>
  ),
}));

const confirmFn = vi.fn();
const rejectFn = vi.fn();

vi.mock("@/api/modules/admin/expertTeams", () => ({
  adminExpertTeamsApi: {
    confirmChangeRequest: (...args: unknown[]) => confirmFn(...args),
    rejectChangeRequest: (...args: unknown[]) => rejectFn(...args),
  },
}));

import TeamChangeCard from "./TeamChangeCard";
import type { ToolCallContent } from "../shared/types";

// ── 测试数据构造 ────────────────────────────────────────────────────────
function makeContent(result: unknown): ToolCallContent {
  return {
    type: "tool_call",
    id: "tc-1",
    name: "team_prepare_change",
    status: "done",
    params: { team_id: "team-abc" },
    result: JSON.stringify(result),
  };
}

const PENDING_RESULT = {
  request_id: "req-1",
  team_id: "team-abc",
  kind: "save_draft",
  status: "pending",
  diff: {
    description: { old: "旧描述", new: "新描述" },
    mode: { old: "pipeline", new: "graph" },
  },
  validation: { ok: true, issues: [] },
  base_revision: 3,
};

afterEach(() => {
  confirmFn.mockReset();
  rejectFn.mockReset();
});

// ── 测试用例 ────────────────────────────────────────────────────────────
describe("TeamChangeCard", () => {
  it("pending 态渲染差异卡 + 确认/拒绝按钮", () => {
    render(<TeamChangeCard content={makeContent(PENDING_RESULT)} />);

    // 差异字段渲染
    expect(screen.getByText("description")).toBeTruthy();
    expect(screen.getByText(/-旧描述/)).toBeTruthy();
    expect(screen.getByText(/\+新描述/)).toBeTruthy();

    // 校验通过标签
    expect(screen.getByText("校验通过")).toBeTruthy();

    // 操作按钮
    expect(screen.getByText("保存草稿")).toBeTruthy();
    expect(screen.getByText("拒绝")).toBeTruthy();
  });

  it("确认成功后状态变为 applied 并 dispatch 事件", async () => {
    confirmFn.mockResolvedValue({ request_id: "req-1", status: "applied", team: null });

    const listener = vi.fn();
    window.addEventListener("qwenpaw:team-config-changed", listener);

    render(<TeamChangeCard content={makeContent(PENDING_RESULT)} />);

    // 点击确认按钮
    fireEvent.click(screen.getByText("保存草稿"));

    await waitFor(() => {
      expect(confirmFn).toHaveBeenCalledWith("team-abc", "req-1");
    });

    // 状态变为已生效
    expect(screen.getByText("已生效")).toBeTruthy();
    // 配置已写入提示
    expect(screen.getByText(/配置已写入草稿/)).toBeTruthy();

    // DOM 事件已触发
    expect(listener).toHaveBeenCalledTimes(1);
    const evt = listener.mock.calls[0][0] as CustomEvent;
    expect(evt.detail).toEqual({ teamId: "team-abc" });

    window.removeEventListener("qwenpaw:team-config-changed", listener);
  });

  it("拒绝后状态变为 rejected 并 dispatch 事件", async () => {
    rejectFn.mockResolvedValue({ request_id: "req-1", status: "rejected" });

    const listener = vi.fn();
    window.addEventListener("qwenpaw:team-config-changed", listener);

    render(<TeamChangeCard content={makeContent(PENDING_RESULT)} />);

    fireEvent.click(screen.getByText("拒绝"));

    await waitFor(() => {
      expect(rejectFn).toHaveBeenCalledWith("team-abc", "req-1");
    });

    expect(screen.getByText("已拒绝")).toBeTruthy();
    expect(screen.getByText(/变更已取消/)).toBeTruthy();
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener("qwenpaw:team-config-changed", listener);
  });

  it("API 失败时显示错误信息", async () => {
    confirmFn.mockRejectedValue(new Error("网络超时"));

    render(<TeamChangeCard content={makeContent(PENDING_RESULT)} />);

    fireEvent.click(screen.getByText("保存草稿"));

    await waitFor(() => {
      expect(screen.getByText("网络超时")).toBeTruthy();
    });

    // 按钮应恢复可操作（loading 结束）
    expect(screen.getByText("保存草稿")).toBeTruthy();
  });

  it("工具执行中展示通用壳（不渲染差异卡）", () => {
    const callingContent: ToolCallContent = {
      type: "tool_call",
      id: "tc-2",
      name: "team_prepare_change",
      status: "calling",
      params: { team_id: "team-abc" },
    };

    render(<TeamChangeCard content={callingContent} />);

    // 通用壳标题
    expect(screen.getByTestId("shell-title")).toBeTruthy();
    // 不应有确认按钮
    expect(screen.queryByText("保存草稿")).toBeNull();
    expect(screen.queryByText("拒绝")).toBeNull();
  });

  it("publish 类型显示发布摘要而非差异卡", () => {
    const publishResult = {
      request_id: "req-2",
      team_id: "team-abc",
      kind: "publish",
      status: "pending",
      current_version: 3,
      draft_revision: 5,
      member_count: 4,
      validation: { ok: false, issues: ["缺少 lead 角色"] },
    };

    render(<TeamChangeCard content={makeContent(publishResult)} />);

    // 发布摘要
    expect(screen.getByText(/当前版本/)).toBeTruthy();
    expect(screen.getByText(/v3/)).toBeTruthy();
    expect(screen.getByText(/草稿修订/)).toBeTruthy();
    expect(screen.getByText(/#5/)).toBeTruthy();
    expect(screen.getByText(/成员数/)).toBeTruthy();
    expect(screen.getByText("4")).toBeTruthy();

    // 校验问题
    expect(screen.getByText("缺少 lead 角色")).toBeTruthy();

    // 发布确认按钮文案
    expect(screen.getByText("确认发布")).toBeTruthy();
  });
});
