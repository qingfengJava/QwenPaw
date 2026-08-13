/**
 * admin/grants.ts — `/admin/grants/{agents,models}` client (M4-3 backend).
 *
 * Grant maps are keyed by resource id (agent id / model key); a resource
 * absent from the map is unrestricted.
 */
import { request } from "../../request";
import type { GrantRecord } from "./types";

export interface GrantBody {
  roles: string[];
  users: string[];
  teams: string[];
  description?: string;
}

const enc = encodeURIComponent;

export const adminGrantsApi = {
  listAgents: () => request<Record<string, GrantRecord>>("/admin/grants/agents"),

  putAgent: (agentId: string, body: GrantBody) =>
    request<GrantRecord>(`/admin/grants/agents/${enc(agentId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  removeAgent: (agentId: string) =>
    request<void>(`/admin/grants/agents/${enc(agentId)}`, {
      method: "DELETE",
    }),

  listModels: () => request<Record<string, GrantRecord>>("/admin/grants/models"),

  // Model keys contain "/" (e.g. "provider/model"); the backend route
  // declares `{model_key:path}`, so keep the slashes intact.
  putModel: (modelKey: string, body: GrantBody) =>
    request<GrantRecord>(
      `/admin/grants/models/${modelKey.split("/").map(enc).join("/")}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  removeModel: (modelKey: string) =>
    request<void>(
      `/admin/grants/models/${modelKey.split("/").map(enc).join("/")}`,
      { method: "DELETE" },
    ),
};
