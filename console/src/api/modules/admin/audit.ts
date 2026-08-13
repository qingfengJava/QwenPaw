/**
 * admin/audit.ts — `/admin/audit` client (governance audit query).
 */
import { request } from "../../request";
import type { AuditPage } from "./types";

export interface AuditQuery {
  workspace_dir?: string;
  agent_id?: string;
  tool_name?: string;
  decision?: string;
  since?: number;
  until?: number;
  limit?: number;
  offset?: number;
}

export const adminAuditApi = {
  query: (q: AuditQuery = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(q)) {
      if (value === undefined || value === "") continue;
      params.set(key, String(value));
    }
    const qs = params.toString();
    return request<AuditPage>(`/admin/audit${qs ? `?${qs}` : ""}`);
  },
};
