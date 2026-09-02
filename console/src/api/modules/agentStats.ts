import { request, type RequestOptions } from "../request";
import type { AgentStatsSummary } from "../types/agentStats";

export interface GetAgentStatsParams {
  start_date: string;
  end_date: string;
}

/** 概览卡/档案栏共用的轻量统计 brief。 */
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

/** 与 listChannels 同模式：显式 agentId 作 X-Agent-Id，未传走借壳通道。 */
function agentOpts(agentId?: string): RequestOptions {
  const opts: RequestOptions = {};
  if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
  return opts;
}

export const agentStatsApi = {
  getAgentStats: (params: GetAgentStatsParams) =>
    request<AgentStatsSummary>(
      `/agent-stats?start_date=${encodeURIComponent(
        params.start_date,
      )}&end_date=${encodeURIComponent(params.end_date)}`,
    ),

  getAgentBriefStats: (agentId?: string) =>
    request<AgentBriefStats>("/agent-stats/summary-brief", agentOpts(agentId)),
};
