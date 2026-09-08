/**
 * Run-log API — list/query agent run logs and fetch per-run trace detail.
 *
 * Backend: GET /api/agents/{agentId}/run-logs (index JSONL) and
 * GET /api/agents/{agentId}/run-logs/{runId} (inbox trace file).
 */
import { request } from "../request";

/** One row of the day-sharded run-log index. */
export interface RunLogItem {
  run_id: string;
  agent_id: string;
  session_id: string;
  chat_id?: string;
  user_id?: string;
  channel?: string;
  source?: string;
  environment?: string;
  query_preview?: string;
  status: string;
  started_at: number;
  finished_at?: number | null;
  duration_ms?: number | null;
  total_tokens?: number;
  /** Actually-used model name (fallback-corrected by the finish hook). */
  model?: string;
  /** Agent publish version (AgentProfileConfig.version). */
  version?: string;
  /** QwenPaw app version (legacy rows may only carry this). */
  app_version?: string;
  error?: string | null;
}

export interface RunLogListResponse {
  items: RunLogItem[];
  total: number;
}

/** One session-delta event inside a run trace. */
export interface RunLogTraceEvent {
  at: number | null;
  event: Record<string, unknown>;
}

/** Full per-run trace payload (meta + events). */
export interface RunLogTrace {
  run_id: string;
  created_at: number;
  completed_at?: number | null;
  status: string;
  error?: string;
  meta?: {
    source?: string;
    session_id?: string;
    root_session_id?: string;
    agent_id?: string;
    user_id?: string;
    channel?: string;
    environment?: string;
    query?: string | null;
    model?: string;
    /** Agent publish version. */
    version?: string;
    app_version?: string;
  };
  events: RunLogTraceEvent[];
}

export interface RunLogListParams {
  status?: string;
  channel?: string;
  source?: string;
  environment?: string;
  q?: string;
  /** Epoch seconds, inclusive. */
  start?: number;
  /** Epoch seconds, inclusive. */
  end?: number;
  limit?: number;
  offset?: number;
}

export const runLogsApi = {
  /**
   * List run logs newest-first (server-side filters + paging).
   * `agentId` scopes the data domain (also passed as `agent_id` query
   * so the backend needs no header-based fallback).
   */
  listRunLogs: (
    params: RunLogListParams | undefined,
    agentId: string,
  ): Promise<RunLogListResponse> => {
    const searchParams = new URLSearchParams();
    if (agentId) searchParams.append("agent_id", agentId);
    if (params?.status) searchParams.append("status", params.status);
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.source) searchParams.append("source", params.source);
    if (params?.environment) {
      searchParams.append("environment", params.environment);
    }
    if (params?.q) searchParams.append("q", params.q);
    if (params?.start !== undefined) {
      searchParams.append("start", String(params.start));
    }
    if (params?.end !== undefined) {
      searchParams.append("end", String(params.end));
    }
    if (params?.limit !== undefined) {
      searchParams.append("limit", String(params.limit));
    }
    if (params?.offset !== undefined) {
      searchParams.append("offset", String(params.offset));
    }
    const query = searchParams.toString();
    return request<RunLogListResponse>(
      `/agents/${encodeURIComponent(agentId)}/run-logs${
        query ? `?${query}` : ""
      }`,
    );
  },

  /** Fetch the full trace (meta + events) for one run. */
  getRunLog: (agentId: string, runId: string): Promise<RunLogTrace> =>
    request<RunLogTrace>(
      `/agents/${encodeURIComponent(agentId)}/run-logs/${encodeURIComponent(
        runId,
      )}`,
    ),
};
