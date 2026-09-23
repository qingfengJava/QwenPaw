import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => {
  const apiMocks = {
    startHubSkillInstall: vi.fn(),
    getHubSkillInstallStatus: vi.fn(),
    cancelHubSkillInstall: vi.fn(),
    importPoolSkillFromHub: vi.fn(),
    downloadSkillPoolSkill: vi.fn(),
  };
  const invalidateSkillCacheMock = vi.fn();
  const notifySkillChangeMock = vi.fn();
  return { apiMocks, invalidateSkillCacheMock, notifySkillChangeMock };
});

vi.mock("../../../api", () => ({
  default: hoisted.apiMocks,
}));

vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: hoisted.invalidateSkillCacheMock,
}));

vi.mock("../../../utils/skillChangeEvents", () => ({
  notifySkillChange: hoisted.notifySkillChangeMock,
}));

import type { MarketResult } from "../../../api/modules/market";
import {
  useMarketInstall,
} from "./useMarketInstall";

const apiMocks = hoisted.apiMocks as Record<string, ReturnType<typeof vi.fn>>;

function makeResult(overrides: Partial<MarketResult> = {}): MarketResult {
  return {
    source: "modelscope",
    slug: "skill-creator",
    name: "skill-creator",
    description: "",
    source_url: "https://modelscope.cn/skills/skill-creator",
    ...overrides,
  } as MarketResult;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useMarketInstall pool deliver flow", () => {
  it("pool install with deliverAgentId downloads the skill to the agent", async () => {
    apiMocks.importPoolSkillFromHub.mockResolvedValue({
      installed: true,
      name: "skill-creator",
      enabled: false,
      source_url: "u",
    });
    apiMocks.downloadSkillPoolSkill.mockResolvedValue({ downloaded: [] });

    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", deliverAgentId: "agent-1" }),
    );

    act(() => {
      result.current.enqueue([makeResult()], "pool");
    });

    await waitFor(() => {
      const item = result.current.queue[0];
      expect(item?.status).toBe("completed");
    });

    expect(apiMocks.importPoolSkillFromHub).toHaveBeenCalledWith({
      bundle_url: "https://modelscope.cn/skills/skill-creator",
      version: undefined,
      target_name: undefined,
    });
    expect(apiMocks.downloadSkillPoolSkill).toHaveBeenCalledWith({
      skill_name: "skill-creator",
      targets: [{ workspace_id: "agent-1" }],
    });
    expect(result.current.queue[0]?.deliverAgentId).toBe("agent-1");
  });

  it("deliver failure downgrades to a partial-success message", async () => {
    apiMocks.importPoolSkillFromHub.mockResolvedValue({
      installed: true,
      name: "skill-creator",
      enabled: false,
      source_url: "u",
    });
    apiMocks.downloadSkillPoolSkill.mockRejectedValue(
      new Error("deliver boom"),
    );

    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1", deliverAgentId: "agent-1" }),
    );

    act(() => {
      result.current.enqueue([makeResult()], "pool");
    });

    await waitFor(() => {
      const item = result.current.queue[0];
      expect(item?.status).toBe("completed");
      expect(item?.message).toBe("__DELIVER_FAILED__");
    });
    // 安装本身不因分发失败而标记 failed
    expect(result.current.queue[0]?.installedName).toBe("skill-creator");
  });

  it("pool install without deliverAgentId skips the download step", async () => {
    apiMocks.importPoolSkillFromHub.mockResolvedValue({
      installed: true,
      name: "skill-creator",
      enabled: false,
      source_url: "u",
    });

    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1" }),
    );

    act(() => {
      result.current.enqueue([makeResult()], "pool");
    });

    await waitFor(() => {
      expect(result.current.queue[0]?.status).toBe("completed");
    });
    expect(apiMocks.downloadSkillPoolSkill).not.toHaveBeenCalled();
    expect(result.current.queue[0]?.deliverAgentId).toBeUndefined();
  });
});

describe("useMarketInstall workspace conflict flow", () => {
  function makeTaskStatus(overrides: Record<string, unknown>) {
    return {
      task_id: "t1",
      bundle_url: "u",
      version: "",
      enable: true,
      status: "pending",
      error: null,
      result: null,
      created_at: 0,
      updated_at: 0,
      ...overrides,
    };
  }

  it("records suggestedName from conflicts and retries with it", async () => {
    apiMocks.startHubSkillInstall.mockResolvedValue(
      makeTaskStatus({ task_id: "t1" }),
    );
    apiMocks.getHubSkillInstallStatus
      .mockResolvedValueOnce(
        makeTaskStatus({
          status: "failed",
          error: "Failed to create skill 'skill-creator'.",
          result: {
            conflicts: [
              { reason: "conflict", suggested_name: "skill-creator-2" },
            ],
          },
        }),
      )
      .mockResolvedValue(
        makeTaskStatus({
          status: "completed",
          result: { installed: true, name: "skill-creator-2" },
        }),
      );

    const { result } = renderHook(() =>
      useMarketInstall({ selectedAgent: "agent-1" }),
    );

    act(() => {
      result.current.enqueue([makeResult()], "workspace");
    });

    await waitFor(() => {
      expect(result.current.queue[0]?.status).toBe("failed");
    });
    expect(result.current.queue[0]?.suggestedName).toBe("skill-creator-2");

    act(() => {
      result.current.retry(result.current.queue[0].id, "skill-creator-2");
    });

    await waitFor(() => {
      expect(result.current.queue[0]?.status).toBe("completed");
    });
    // 重试时把建议名作为 target_name 传入
    expect(apiMocks.startHubSkillInstall).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_name: "skill-creator-2" }),
      "agent-1",
    );
  });
});
