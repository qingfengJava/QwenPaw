/**
 * admin/kb.ts — `/admin/kb` client (knowledge base fleet management).
 */
import { request } from "../../request";
import type { KbDocumentView, KbScope, KnowledgeBase } from "./types";

/** POST /admin/kb/search-test body (`SearchTestBody` in admin/kb.py, T11). */
export interface KbSearchTestBody {
  query: string;
  /** Required by the admin endpoint (single-space tuning pass). */
  kb_id: string;
  top_k?: number;
}

/** One search-test hit; `heading_path` is a joined string (chunker contract). */
export interface KbSearchTestHit {
  chunk_id: string;
  doc_id: string;
  seq: number;
  title: string;
  text: string;
  score: number;
  heading_path: string;
}

export interface KbSearchTestResult {
  kb_id: string;
  hits: KbSearchTestHit[];
}

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

/** 生命周期操作动作（`AdminReviewBody.action`，T3）。 */
export type KbReviewAction = "submit" | "approve" | "reject" | "archive";

export interface KbReviewResult {
  doc_id: string;
  knowledge_status: string;
  review_note: string;
}

/** 一条审核流水（新→旧）。 */
export interface KbReviewLogRow {
  id: number;
  action: string;
  reviewer: string;
  comment: string;
  created_at: string;
}

/** 一条知识冲突（`kb_conflicts`，T3）。 */
export interface KbConflictRow {
  id: number;
  document_id_a: string;
  document_id_b: string;
  conflict_type: string;
  priority: number;
  resolution_status: string;
  resolved_by: string;
  created_at: string;
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

  /** POST /admin/kb/search-test — engine top-k + score detail (no ACL narrowing). 503 when the pg plane is down. */
  searchTest: (body: KbSearchTestBody) =>
    request<KbSearchTestResult>("/admin/kb/search-test", {
      method: "POST",
      body: JSON.stringify({
        query: body.query,
        kb_id: body.kb_id,
        top_k: body.top_k ?? 5,
      }),
    }),

  /** POST /…/review — 推进知识生命周期（T3；非法流转 400）。 */
  review: (kbId: string, docId: string, action: KbReviewAction, comment = "") =>
    request<KbReviewResult>(
      `/admin/kb/${enc(kbId)}/documents/${enc(docId)}/review`,
      {
        method: "POST",
        body: JSON.stringify({ action, comment }),
      },
    ),

  /** GET /…/reviews — 一份文档的审核流水（新→旧）。 */
  listReviews: (kbId: string, docId: string) =>
    request<KbReviewLogRow[]>(
      `/admin/kb/${enc(kbId)}/documents/${enc(docId)}/reviews`,
    ),

  /** GET /…/conflicts — 冲突清单（status=open/resolved/空=全态）。 */
  listConflicts: (kbId: string, status = "") =>
    request<KbConflictRow[]>(
      `/admin/kb/${enc(kbId)}/conflicts${status ? `?status=${enc(status)}` : ""}`,
    ),

  /** POST /…/conflicts/{id}/resolve — 解决一个 open 冲突。 */
  resolveConflict: (kbId: string, conflictId: string | number) =>
    request<Record<string, never>>(
      `/admin/kb/${enc(kbId)}/conflicts/${enc(String(conflictId))}/resolve`,
      { method: "POST" },
    ),
};
