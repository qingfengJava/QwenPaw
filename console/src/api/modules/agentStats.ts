import { request, type RequestOptions } from "../request";
import type { AgentStatsSummary } from "../types/agentStats";

export interface GetAgentStatsParams {
  start_date: string;
  end_date: string;
}

export interface LlmToolDaily {
  date: string;
  agent_llm_calls: number;
  tool_calls: number;
}

function dateQuery(params: GetAgentStatsParams): string {
  const search = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  return `?${search.toString()}`;
}

/** 概览与档案栏共用的轻量统计 brief。 */
export interface AgentBriefDaily {
  date: string;
  chats: number;
  messages: number;
}

export interface AgentBriefStats {
  today_chats: number;
  total_chats: number;
  total_messages: number;
  total_tokens: number;
  active_sessions: number;
  recent_daily: AgentBriefDaily[];
}

/** 与 listChannels 同模式：显式 agentId 走 X-Agent-Id，未传走借壳通道。 */
function agentOpts(agentId?: string): RequestOptions {
  const opts: RequestOptions = {};
  if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
  return opts;
}

export const agentStatsApi = {
  getAgentStats: (params: GetAgentStatsParams) =>
    request<AgentStatsSummary>(`/agent-stats${dateQuery(params)}`),
  getGlobalLlmToolTrend: (
    params: GetAgentStatsParams,
    options?: { signal?: AbortSignal },
  ) =>
    request<LlmToolDaily[]>(`/agent-stats/llm-tool-trend${dateQuery(params)}`, {
      timeout: 60_000,
      signal: options?.signal,
    }),
  getAgentBriefStats: (agentId?: string) =>
    request<AgentBriefStats>("/agent-stats/summary-brief", agentOpts(agentId)),
};
