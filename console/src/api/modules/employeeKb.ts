/**
 * employeeKb.ts — `/kb` employee-plane client (KB phase 1, T12).
 *
 * Mirrors `src/qwenpaw/app/routers/kb.py` (employee document plane) and
 * the agent kb-bindings endpoints in `routers/agents.py` (T7). Field
 * names match the backend response shapes verbatim (snake_case).
 *
 * Error semantics to surface in UI (see plan T12):
 * - 503: pg authoritative plane unavailable (tree/detail/PUT/upload)
 * - 400: value-level rejection (e.g. blank content_md)
 * - 403: not owner / missing kb:write on a managed write
 */
import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/** One accessible knowledge space (`KbView` in kb.py). */
export interface KbSpaceView {
  id: string;
  name: string;
  scope: string;
  owner_id: string;
  team_id: string;
  description: string;
}

export interface KbCreateSpaceBody {
  name: string;
  description?: string;
}

/** Path-aggregated tree node from `GET /kb/{spaceId}/tree`. */
export interface KbTreeNode {
  name: string;
  path: string;
  /** null for pure directory nodes. */
  doc_id: string | null;
  title: string;
  ingest_status: string;
  children: KbTreeNode[];
}

export interface KbTreeResponse {
  kb_id: string;
  nodes: KbTreeNode[];
}

/** Document detail: authoritative full markdown + version + status. */
export interface KbDocDetail {
  doc_id: string;
  kb_id: string;
  title: string;
  path: string;
  source: string;
  ingest_status: string;
  version: number;
  content_md: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
}

/** PUT save response: version bump + re-index outcome. */
export interface KbDocSaveResult {
  doc_id: string;
  version: number;
  ingest_status: string;
  chunk_count: number;
}

/** multipart upload response. */
export interface KbUploadResult {
  doc_id: string;
  path: string;
  ingest_status: string;
  chunk_count: number;
}

/** One chunk preview row (`heading_path` is a joined string, not array). */
export interface KbChunk {
  chunk_id: string;
  seq: number;
  text: string;
  heading_path: string;
  parent_seq: number | null;
}

export interface KbSearchBody {
  query: string;
  /** Omitted = search every accessible space. */
  kb_id?: string;
  top_k?: number;
}

export interface KbSearchHit {
  kb_id: string;
  kb_name: string;
  doc_id: string;
  title: string;
  text: string;
  score: number;
}

export interface KbSearchResponse {
  hits: KbSearchHit[];
}

/** One binding row enriched with space name/scope (`kb/bindings.py`). */
export interface KbBindingRow {
  agent_id: string;
  space_id: string;
  space_name: string;
  scope: string;
  granted_by: string;
  remark: string;
  created_at: string;
}

/** PUT binding response: full row + created flag (201 new / 200 idempotent). */
export type KbBindingResult = KbBindingRow & { created: boolean };

const enc = encodeURIComponent;

export const employeeKbApi = {
  /** GET /kb — every knowledge base the caller may read (ACL-filtered). */
  listSpaces: () => request<KbSpaceView[]>("/kb"),

  /** POST /kb (201) — create a personal space owned by the caller. */
  createSpace: (body: KbCreateSpaceBody) =>
    request<KbSpaceView>("/kb", {
      method: "POST",
      body: JSON.stringify({ name: body.name, description: body.description ?? "" }),
    }),

  /** GET /kb/{spaceId}/tree — path-aggregated document tree (pg plane). */
  getTree: (spaceId: string) =>
    request<KbTreeResponse>(`/kb/${enc(spaceId)}/tree`),

  /** GET /kb/{spaceId}/documents/{docId} — full markdown detail. */
  getDoc: (spaceId: string, docId: string) =>
    request<KbDocDetail>(`/kb/${enc(spaceId)}/documents/${enc(docId)}`),

  /** PUT /kb/{spaceId}/documents/{docId} — content_md upsert (auto version+1). */
  saveDoc: (spaceId: string, docId: string, contentMd: string) =>
    request<KbDocSaveResult>(`/kb/${enc(spaceId)}/documents/${enc(docId)}`, {
      method: "PUT",
      body: JSON.stringify({ content_md: contentMd }),
    }),

  /**
   * POST /kb/{spaceId}/documents/upload (201) — multipart with the
   * `file` field. Goes through raw fetch (like chatApi.uploadFile)
   * because request() would force a JSON Content-Type onto FormData
   * and break the browser-generated multipart boundary.
   */
  uploadDoc: async (spaceId: string, file: File): Promise<KbUploadResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(
      getApiUrl(`/kb/${enc(spaceId)}/documents/upload`),
      {
        method: "POST",
        headers: buildAuthHeaders(),
        body: formData,
      },
    );
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      const err = new Error(
        `Upload failed: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
      // Structured status for kbRequestError mapping (503/403/404)
      (err as Error & { status?: number }).status = response.status;
      throw err;
    }
    return (await response.json()) as KbUploadResult;
  },

  /** GET /kb/{spaceId}/documents/{docId}/chunks — seq-ascending preview. */
  listChunks: (spaceId: string, docId: string) =>
    request<KbChunk[]>(`/kb/${enc(spaceId)}/documents/${enc(docId)}/chunks`),

  /** POST /kb/search — hybrid search across one or all accessible spaces. */
  search: (body: KbSearchBody) =>
    request<KbSearchResponse>("/kb/search", {
      method: "POST",
      body: JSON.stringify({
        query: body.query,
        ...(body.kb_id ? { kb_id: body.kb_id } : {}),
        top_k: body.top_k ?? 5,
      }),
    }),

  /**
   * PUT /agents/{agentId}/kb-bindings — bind one space (T7). Returns the
   * full binding row plus `created` so callers never branch on status.
   */
  bindAgent: (agentId: string, spaceId: string, remark = "") =>
    request<KbBindingResult>(`/agents/${enc(agentId)}/kb-bindings`, {
      method: "PUT",
      body: JSON.stringify({ space_id: spaceId, remark }),
    }),

  /** GET /agents/{agentId}/kb-bindings — rows enriched with name/scope. */
  listBindings: (agentId: string) =>
    request<KbBindingRow[]>(`/agents/${enc(agentId)}/kb-bindings`),

  /** DELETE /agents/{agentId}/kb-bindings/{spaceId} (204). */
  unbind: (agentId: string, spaceId: string) =>
    request<void>(`/agents/${enc(agentId)}/kb-bindings/${enc(spaceId)}`, {
      method: "DELETE",
    }),
};

// ─────────────────────────────────────────────────────────────────────────────
// 员工知识工作流（T6/T7）：我的库 × 我的专家绑定（/xian/knowledge/*）
// ─────────────────────────────────────────────────────────────────────────────

/** 我拥有的个人库（绑定流下拉源）。 */
export interface MyKbView {
  id: string;
  name: string;
  description: string;
  scope: string;
}

/** 我的专家（市场卡片投影的最小字段集）。 */
export interface MyExpertView {
  id: string;
  name: string;
  description: string;
}

/** 一条「库 → 我的专家」绑定（行 + 专家名）。 */
export interface ExpertBindingView {
  expert_id: string;
  expert_name: string;
  space_id: string;
  granted_by: string;
  created_at: string;
}

export const employeeKnowledgeApi = {
  /** GET /xian/knowledge/bases — 我拥有的 personal 库。 */
  listMyBases: () => request<MyKbView[]>("/xian/knowledge/bases"),

  /** GET /xian/experts?scope=mine — 我的专家列表（绑定目标域）。 */
  listMyExperts: () =>
    request<MyExpertView[]>("/xian/experts?scope=mine"),

  /** GET /xian/knowledge/bases/{kbId}/expert-bindings — 已绑的我的专家。 */
  listExpertBindings: (kbId: string) =>
    request<ExpertBindingView[]>(
      `/xian/knowledge/bases/${enc(kbId)}/expert-bindings`,
    ),

  /** PUT /xian/knowledge/bases/{kbId}/expert-bindings — 绑定我的专家。 */
  bindExpert: (kbId: string, expertId: string) =>
    request<KbBindingResult & { created: boolean }>(
      `/xian/knowledge/bases/${enc(kbId)}/expert-bindings`,
      {
        method: "PUT",
        body: JSON.stringify({ expert_id: expertId }),
      },
    ),

  /** DELETE /xian/knowledge/bases/{kbId}/expert-bindings/{expertId} (204)。 */
  unbindExpert: (kbId: string, expertId: string) =>
    request<void>(
      `/xian/knowledge/bases/${enc(kbId)}/expert-bindings/${enc(expertId)}`,
      { method: "DELETE" },
    ),
};
