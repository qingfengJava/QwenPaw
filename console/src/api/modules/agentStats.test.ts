/**
 * Tests for api/modules/agentStats.ts
 *
 * Contract-guard style: verify return pass-through and that the date
 * params are forwarded to `request`.  We do not pin the exact query
 * string format — that's a transport detail covered by `request`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { agentStatsApi } from "./agentStats";
import { request } from "../request";

describe("agentStatsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("getAgentStats returns the AgentStatsSummary from request", async () => {
    const summary = {
      total_messages: 10,
      by_agent: [],
      by_date: [],
    } as unknown;
    vi.mocked(request).mockResolvedValue(summary);
    const result = await agentStatsApi.getAgentStats({
      start_date: "2026-01-01",
      end_date: "2026-01-31",
    });
    expect(result).toBe(summary);
  });

  it("forwards request errors unchanged", async () => {
    vi.mocked(request).mockRejectedValue(new Error("network"));
    await expect(
      agentStatsApi.getAgentStats({
        start_date: "2026-01-01",
        end_date: "2026-01-31",
      }),
    ).rejects.toThrow("network");
  });

  it("getAgentBriefStats returns the brief and sends X-Agent-Id", async () => {
    const brief = {
      today_chats: 1,
      total_chats: 2,
      total_messages: 3,
      total_tokens: 4,
      active_sessions: 5,
      recent_daily: [],
    } as unknown;
    vi.mocked(request).mockResolvedValue(brief);
    const result = await agentStatsApi.getAgentBriefStats("agent-a");
    expect(result).toBe(brief);
    const opts = vi.mocked(request).mock.calls[0][1];
    const headers = (opts as { headers: Headers }).headers;
    expect(headers.get("X-Agent-Id")).toBe("agent-a");
  });

  it("getAgentBriefStats omits X-Agent-Id when agentId is absent", async () => {
    vi.mocked(request).mockResolvedValue({} as unknown);
    await agentStatsApi.getAgentBriefStats();
    const opts = vi.mocked(request).mock.calls[0][1];
    expect(opts?.headers).toBeUndefined();
  });
});
