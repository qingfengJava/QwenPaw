import { request, type RequestOptions } from "../request";
import type { HeartbeatConfig } from "../types/heartbeat";

/** 与 listChannels 同模式：显式 agentId 作 X-Agent-Id，未传走借壳通道。 */
function agentOpts(agentId?: string): RequestOptions {
  const opts: RequestOptions = {};
  if (agentId) opts.headers = new Headers({ "X-Agent-Id": agentId });
  return opts;
}

export const heartbeatApi = {
  getHeartbeatConfig: (agentId?: string) =>
    request<HeartbeatConfig>("/config/heartbeat", agentOpts(agentId)),

  updateHeartbeatConfig: (body: HeartbeatConfig, agentId?: string) =>
    request<HeartbeatConfig>("/config/heartbeat", {
      ...agentOpts(agentId),
      method: "PUT",
      body: JSON.stringify(body),
    }),

  runHeartbeatNow: (agentId?: string) =>
    request<{ started: boolean }>("/config/heartbeat/run", {
      ...agentOpts(agentId),
      method: "POST",
    }),
};
