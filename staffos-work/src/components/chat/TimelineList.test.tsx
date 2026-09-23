// @vitest-environment jsdom
/**
 * TimelineList team_run 卡片渲染测试（聊天双态入口）：状态角标 /
 * 团队名 / 汇总摘要 / RunDetail 跳转链接。
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import TimelineList from "./TimelineList";
import type { TimelineItem } from "../../chat/protocol";

afterEach(cleanup);

function renderItems(items: TimelineItem[]) {
  return render(
    <MemoryRouter>
      <TimelineList items={items} streaming={false} />
    </MemoryRouter>,
  );
}

describe("TimelineList team_run 卡片", () => {
  it("占位卡片：团队名 + 状态角标 + 详情链接", () => {
    renderItems([
      {
        kind: "team_run",
        key: "run_run_1",
        runId: "run_1",
        teamName: "技术专家团",
        status: "running",
      },
    ]);
    expect(screen.getByText("技术专家团 · 专家团任务")).toBeTruthy();
    expect(screen.getByText("执行中")).toBeTruthy();
    const link = screen.getByText("查看任务详情").closest("a")!;
    expect(link.getAttribute("href")).toBe("/runs/run_1");
  });

  it("无摘要时渲染默认占位文案", () => {
    renderItems([
      {
        kind: "team_run",
        key: "run_run_2",
        runId: "run_2",
        status: "planning",
      },
    ]);
    expect(
      screen.getByText("已升级为后台专家团任务，正在拆解 DAG 计划并逐节点推进…"),
    ).toBeTruthy();
  });

  it("完成态：状态角标切换 + 汇总正文展示", () => {
    renderItems([
      {
        kind: "team_run",
        key: "run_run_3",
        runId: "run_3",
        teamName: "技术专家团",
        status: "done",
        summary: "最终交付：登录页方案已完成",
      },
    ]);
    expect(screen.getByText("已完成")).toBeTruthy();
    expect(screen.getByText("最终交付：登录页方案已完成")).toBeTruthy();
  });

  it("熔断态：升级人工角标可见", () => {
    renderItems([
      {
        kind: "team_run",
        key: "run_run_4",
        runId: "run_4",
        status: "escalated",
      },
    ]);
    expect(screen.getByText("已升级人工")).toBeTruthy();
  });
});
