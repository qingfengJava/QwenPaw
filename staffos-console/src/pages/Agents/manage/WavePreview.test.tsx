/**
 * WavePreview 分层测试：waveLayering 纯函数（串行/并行/环依赖）
 * 与组件渲染（波次行、并行徽标、无法分层提示）。
 */
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import WavePreview, { waveLayering } from "./WavePreview";

afterEach(cleanup);

describe("waveLayering（拓扑分层纯函数）", () => {
  it("串行链按依赖顺序逐波排布", () => {
    const { waves, unresolved } = waveLayering([
      { node_key: "a", deps: [] },
      { node_key: "b", deps: ["a"] },
      { node_key: "final-summary", deps: ["b"], node_type: "final" },
    ]);
    expect(waves).toEqual([["a"], ["b"], ["final-summary"]]);
    expect(unresolved).toEqual([]);
  });

  it("fe/be 同 deps → 同一波并行（多工程师并行范式）", () => {
    const { waves, unresolved } = waveLayering([
      { node_key: "requirement", deps: [] },
      { node_key: "architecture", deps: ["requirement"] },
      { node_key: "fe", deps: ["architecture"] },
      { node_key: "be", deps: ["architecture"] },
      { node_key: "final-summary", deps: ["fe", "be"], node_type: "final" },
    ]);
    expect(waves).toEqual([
      ["requirement"],
      ["architecture"],
      ["fe", "be"],
      ["final-summary"],
    ]);
    expect(unresolved).toEqual([]);
  });

  it("环依赖节点进入 unresolved（不进入任何波）", () => {
    const { waves, unresolved } = waveLayering([
      { node_key: "a", deps: ["b"] },
      { node_key: "b", deps: ["a"] },
      { node_key: "final-summary", deps: ["a"], node_type: "final" },
    ]);
    expect(waves).toEqual([]);
    expect(new Set(unresolved)).toEqual(
      new Set(["a", "b", "final-summary"]),
    );
  });

  it("未知 deps 与环同样被报告为 unresolved", () => {
    const { waves, unresolved } = waveLayering([
      { node_key: "a", deps: ["ghost"] },
    ]);
    expect(waves).toEqual([]);
    expect(unresolved).toEqual(["a"]);
  });
});

describe("WavePreview 组件渲染", () => {
  it("并行波渲染「并行」徽标与节点 chip", () => {
    renderWithProviders(
      <WavePreview
        nodesJson={JSON.stringify([
          { node_key: "arch", deps: [] },
          { node_key: "fe", deps: ["arch"] },
          { node_key: "be", deps: ["arch"] },
        ])}
      />,
    );
    expect(screen.getByText("第 1 波")).toBeInTheDocument();
    expect(screen.getByText("第 2 波")).toBeInTheDocument();
    // 同波两节点 → 恰好一个并行徽标
    expect(screen.getAllByText("并行")).toHaveLength(1);
    expect(screen.getByText("fe")).toBeInTheDocument();
    expect(screen.getByText("be")).toBeInTheDocument();
  });

  it("非法 JSON 显示解析错误提示", () => {
    renderWithProviders(<WavePreview nodesJson="{not-json" />);
    expect(screen.getByText(/JSON 无法解析/)).toBeInTheDocument();
  });

  it("空输入显示空态提示", () => {
    renderWithProviders(
      <WavePreview nodesJson="" emptyHint="尚未配置节点" />,
    );
    expect(screen.getByText("尚未配置节点")).toBeInTheDocument();
  });

  it("环依赖显示无法分层提示", () => {
    renderWithProviders(
      <WavePreview
        nodesJson={JSON.stringify([
          { node_key: "a", deps: ["b"] },
          { node_key: "b", deps: ["a"] },
        ])}
      />,
    );
    expect(screen.getByText(/无法分层（环或未知依赖）/)).toBeInTheDocument();
  });
});
