/**
 * admin/ontology.ts — `/admin/ontology` client (ontology runtime, T4/T7).
 *
 * Field names match `qwenpaw.app.ontology.models` verbatim (snake_case).
 * Error semantics for the UI: 503 = ontology plane unavailable (pg
 * enterprise backend required); 400 = validation (ValueError); 404 =
 * path resource missing.
 */
import { request } from "../../request";

const enc = encodeURIComponent;

/** One ontology type node (`/admin/ontology/types`, seed L0/L1). */
export interface OntologyTypeView {
  id: string;
  parent_id: string | null;
  name: string;
  name_en: string;
  layer: string;
  description: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface OntologyObjectView {
  id: string;
  type_id: string;
  name: string;
  aliases: string[];
  attributes: Record<string, unknown>;
  status: string;
  source: string;
  description: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface OntologyObjectBody {
  type_id: string;
  name: string;
  aliases?: string[];
  attributes?: Record<string, unknown>;
  description?: string;
}

/** Relation row — fields match `OntologyRelation` (models.py) verbatim. */
export interface OntologyRelationView {
  id: string;
  type: string;
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  valid_from: string | null;
  valid_to: string | null;
  confidence: number;
  source: string;
  evidence_refs: string[];
  created_at: string | null;
}

export interface OntologyRelationBody {
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  type: string;
}

/** GET /objects/{id}/relations 双向列表返回（outbound + inbound）。 */
export interface OntologyRelationsPairView {
  outbound: OntologyRelationView[];
  inbound: OntologyRelationView[];
}

/**
 * One object↔document link (`kb_object_links`, T4) — fields match
 * `KbObjectLink` (models.py) verbatim（kb_space_id / kb_document_id / object_type）.
 */
export interface KbObjectLinkView {
  id: string;
  kb_space_id: string;
  kb_document_id: string;
  object_type: string;
  object_id: string;
  relation: string;
  created_at: string | null;
}

export interface KbObjectLinkBody {
  kb_space_id: string;
  kb_document_id: string;
  object_type: string;
  relation?: string;
}

export const adminOntologyApi = {
  listTypes: () => request<OntologyTypeView[]>("/admin/ontology/types"),

  listObjects: (params: { q?: string; type_id?: string; limit?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.q) search.set("q", params.q);
    if (params.type_id) search.set("type_id", params.type_id);
    if (params.limit) search.set("limit", String(params.limit));
    const qs = search.toString();
    return request<OntologyObjectView[]>(
      `/admin/ontology/objects${qs ? `?${qs}` : ""}`,
    );
  },

  createObject: (body: OntologyObjectBody) =>
    request<OntologyObjectView>("/admin/ontology/objects", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getObject: (objectId: string) =>
    request<OntologyObjectView>(`/admin/ontology/objects/${enc(objectId)}`),

  updateObject: (objectId: string, fields: Partial<OntologyObjectBody>) =>
    request<OntologyObjectView>(`/admin/ontology/objects/${enc(objectId)}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    }),

  /** DELETE /objects/{id} — soft delete (204). */
  removeObject: (objectId: string) =>
    request<void>(`/admin/ontology/objects/${enc(objectId)}`, {
      method: "DELETE",
    }),

  /** 返回 {outbound, inbound} 双向列表（后端 dict，非数组）。 */
  listObjectRelations: (objectId: string) =>
    request<OntologyRelationsPairView>(
      `/admin/ontology/objects/${enc(objectId)}/relations`,
    ),

  createRelation: (body: OntologyRelationBody) =>
    request<OntologyRelationView>("/admin/ontology/relations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  removeRelation: (relationId: string) =>
    request<void>(`/admin/ontology/relations/${enc(relationId)}`, {
      method: "DELETE",
    }),

  listLinks: (objectId: string) =>
    request<KbObjectLinkView[]>(
      `/admin/ontology/links?object_id=${enc(objectId)}`,
    ),

  createLink: (objectId: string, body: KbObjectLinkBody) =>
    request<KbObjectLinkView>("/admin/ontology/links", {
      method: "POST",
      body: JSON.stringify({ object_id: objectId, ...body }),
    }),

  removeLink: (linkId: string) =>
    request<void>(`/admin/ontology/links/${enc(linkId)}`, {
      method: "DELETE",
    }),
};
