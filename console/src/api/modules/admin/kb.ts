/**
 * admin/kb.ts — `/admin/kb` client (knowledge base fleet management).
 */
import { request } from "../../request";
import type { KbDocumentView, KbScope, KnowledgeBase } from "./types";

export interface KbBody {
  name: string;
  scope: KbScope;
  owner_id?: string;
  team_id?: string;
  description?: string;
  grants_roles?: string[];
  grants_users?: string[];
  grants_teams?: string[];
}

export interface IngestBody {
  text: string;
  title?: string;
  source?: string;
}

export interface IngestResult {
  doc_id: string;
  kb_id: string;
  chunk_count: number;
}

const enc = encodeURIComponent;

export const adminKbApi = {
  list: () => request<KnowledgeBase[]>("/admin/kb"),

  create: (body: KbBody) =>
    request<KnowledgeBase>("/admin/kb", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  remove: (kbId: string) =>
    request<void>(`/admin/kb/${enc(kbId)}`, { method: "DELETE" }),

  ingest: (kbId: string, body: IngestBody) =>
    request<IngestResult>(`/admin/kb/${enc(kbId)}/documents`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listDocuments: (kbId: string) =>
    request<KbDocumentView[]>(`/admin/kb/${enc(kbId)}/documents`),

  removeDocument: (kbId: string, docId: string) =>
    request<void>(`/admin/kb/${enc(kbId)}/documents/${enc(docId)}`, {
      method: "DELETE",
    }),
};
