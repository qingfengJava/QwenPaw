// @vitest-environment jsdom
/**
 * ExpertDetailModal 渲染测试：「专家帮你做」模板行（点击回调携带
 * prompt 作为 kickoff）与「使用案例」卡（title/desc/tags）按详情数据
 * 正确渲染；API 打桩，只关心纯渲染语义。
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ExpertDetailModal from "./ExpertDetailModal";
import type { ExpertDetail } from "../../api/modules";

vi.mock("../../api/modules", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../api/modules")>();
  return {
    ...actual,
    expertApi: {
      ...actual.expertApi,
      detail: vi.fn(),
    },
  };
});

import { expertApi } from "../../api/modules";

afterEach(cleanup);

function makeDetail(overrides: Partial<ExpertDetail> = {}): ExpertDetail {
  return {
    id: "exp_1",
    name: "篇篇红",
    icon: "fa-solid fa-bullhorn",
    description: "公众号增长操盘手",
    version: 1,
    agent_id: "expert_exp_1",
    title: "微信公众号运营专家",
    badge: "官方",
    usage_count: 8,
    system_prompt: "你是「篇篇红」。",
    skills: [],
    teams: [],
    sample_tasks: [
      {
        title: "规划公众号菜单和自动回复体系",
        prompt: "请为我的微信公众号规划一套完整的菜单结构和自动回复体系。",
      },
      {
        title: "设计一场公众号裂变涨粉活动",
        prompt: "请为我们的公众号设计一场裂变涨粉活动。",
      },
    ],
    showcase: [
      {
        title: "本地生活号 3 个月粉丝破万",
        desc: "定位重塑 + 菜单改版 + 每周话题活动组合拳。",
        tags: ["定位重塑", "活动运营"],
      },
    ],
    ...overrides,
  };
}

describe("ExpertDetailModal 运营位渲染", () => {
  it("渲染「专家帮你做」模板行与「使用案例」卡（含 tags）", async () => {
    vi.mocked(expertApi.detail).mockResolvedValue(makeDetail());
    render(
      <ExpertDetailModal expertId="exp_1" onClose={() => undefined} onSummon={() => undefined} />,
    );

    expect(await screen.findByText("专家帮你做")).toBeTruthy();
    expect(screen.getByText("规划公众号菜单和自动回复体系")).toBeTruthy();
    expect(screen.getByText("使用案例")).toBeTruthy();
    expect(screen.getByText("本地生活号 3 个月粉丝破万")).toBeTruthy();
    expect(screen.getByText("定位重塑")).toBeTruthy();
    expect(screen.getByText("活动运营")).toBeTruthy();
  });

  it("点击模板行 → onSummon 携带 (detail, prompt)", async () => {
    vi.mocked(expertApi.detail).mockResolvedValue(makeDetail());
    const onSummon = vi.fn();
    render(
      <ExpertDetailModal expertId="exp_1" onClose={() => undefined} onSummon={onSummon} />,
    );

    fireEvent.click(await screen.findByText("设计一场公众号裂变涨粉活动"));
    expect(onSummon).toHaveBeenCalledTimes(1);
    const [expert, kickoff] = onSummon.mock.calls[0];
    expect(expert.id).toBe("exp_1");
    expect(kickoff).toBe("请为我们的公众号设计一场裂变涨粉活动。");
  });

  it("底部召唤按钮不携带 kickoff（默认开场白路径）", async () => {
    vi.mocked(expertApi.detail).mockResolvedValue(makeDetail());
    const onSummon = vi.fn();
    render(
      <ExpertDetailModal expertId="exp_1" onClose={() => undefined} onSummon={onSummon} />,
    );

    fireEvent.click(await screen.findByText("召唤专家"));
    expect(onSummon).toHaveBeenCalledTimes(1);
    expect(onSummon.mock.calls[0][1]).toBeUndefined();
  });

  it("无运营位数据时两个区块均不渲染", async () => {
    vi.mocked(expertApi.detail).mockResolvedValue(
      makeDetail({ sample_tasks: [], showcase: [] }),
    );
    render(
      <ExpertDetailModal expertId="exp_1" onClose={() => undefined} onSummon={() => undefined} />,
    );

    await waitFor(() =>
      expect(screen.getByText(/篇篇红 · 召唤 8 次/)).toBeTruthy(),
    );
    expect(screen.queryByText("专家帮你做")).toBeNull();
    expect(screen.queryByText("使用案例")).toBeNull();
  });
});
