import { describe, expect, it } from "vitest";

import type { GateInstanceConfig } from "@/api/types";
import {
  buildCustomLoopMode,
  hasDuplicateLoopModeName,
  reorderCustomGates,
} from "./AgentLoopCard";

describe("buildCustomLoopMode", () => {
  it("creates multiple custom modes with unique tab identity", () => {
    const first = buildCustomLoopMode([], "Research", "research", "safe", 1);
    const second = buildCustomLoopMode(
      [first],
      "Research Copy",
      "research",
      "quality",
      2,
    );

    expect(first.id).toBe("research");
    expect(second.id).toBe("research-2");
    expect(second.slash_command).toBe("research-2");
    expect(second.gates.map((gate) => gate.type)).toEqual([
      "iteration",
      "token_budget",
      "doom_loop",
      "independent_verify",
    ]);
    // quality 模板以独立验收收尾（不再用模型自评的 completion 信号门）
    expect(
      second.gates[second.gates.length - 1]?.params.max_repairs,
    ).toBe(1);
  });

  it("keeps the self-graded rubric available as an explicit choice", () => {
    const mode = buildCustomLoopMode([], "Strict", "strict", "safe", 1);

    // safe 模板仍用自评式 qualitative rubric，两套质量门共存
    expect(mode.gates.map((gate) => gate.type)).toContain("qualitative_rubric");
  });

  it("keeps generated identity within backend limits", () => {
    const command = "a".repeat(64);
    const first = buildCustomLoopMode([], "N".repeat(80), command, "safe", 1);
    const second = buildCustomLoopMode([first], "Copy", command, "safe", 2);

    expect(second.id.length).toBeLessThanOrEqual(64);
    expect(second.slash_command.length).toBeLessThanOrEqual(64);
    expect(second.id.endsWith("-2")).toBe(true);
    expect(second.slash_command.endsWith("-2")).toBe(true);
  });
});

describe("reorderCustomGates", () => {
  it("uses the visible pipeline order as the source of truth", () => {
    const gates = [
      { id: "one", type: "iteration" },
      { id: "two", type: "tool_call_budget" },
      { id: "three", type: "doom_loop" },
    ].map(
      (gate) =>
        ({
          ...gate,
          enabled: true,
          params: {},
        }) as GateInstanceConfig,
    );

    expect(reorderCustomGates(gates, 2, 0).map((gate) => gate.id)).toEqual([
      "three",
      "one",
      "two",
    ]);
  });
});

describe("hasDuplicateLoopModeName", () => {
  it("ignores surrounding whitespace and letter case", () => {
    const mode = buildCustomLoopMode([], "Research", "research", "safe", 1);

    expect(hasDuplicateLoopModeName([mode], " research ")).toBe(true);
    expect(hasDuplicateLoopModeName([mode], "Quality")).toBe(false);
    expect(hasDuplicateLoopModeName([mode], "Research", 0)).toBe(false);
  });

  it("matches common Unicode casefold collisions", () => {
    const mode = buildCustomLoopMode([], "Straße", "street", "safe", 1);

    expect(hasDuplicateLoopModeName([mode], "STRASSE")).toBe(true);
  });
});
