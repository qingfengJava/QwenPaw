/**
 * admin/teams.ts — `/admin/teams` client.
 */
import { request } from "../../request";
import type { TeamRecord } from "./types";

export interface TeamBody {
  members: string[];
  description?: string;
}

const enc = encodeURIComponent;

export const adminTeamsApi = {
  list: () => request<TeamRecord[]>("/admin/teams"),

  upsert: (name: string, body: TeamBody) =>
    request<TeamRecord>(`/admin/teams/${enc(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  remove: (name: string) =>
    request<void>(`/admin/teams/${enc(name)}`, { method: "DELETE" }),
};
