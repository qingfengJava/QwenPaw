/**
 * kbErrors.ts — shared KB error mapping (KB phase 1, T12 review fix).
 *
 * Maps request-layer failures onto readable, localized guidance for the
 * Admin knowledge pages. Prefers the structured `status` field that
 * `request()` now attaches to thrown errors; falls back to scanning the
 * message text so native errors (TypeError, mocks, legacy shapes) still
 * map sensibly.
 *
 * Error semantics per plan T12:
 * - 503: pg authoritative plane unavailable (tree/detail/PUT/upload)
 * - 403: not owner / missing kb:write on a managed write
 * - 404: resource missing or already deleted
 */

import type { TFunction } from "i18next";

type ErrorWithStatus = Error & { status?: number };

export function kbRequestError(err: unknown, t: TFunction): string {
  const candidate = err as ErrorWithStatus | null | undefined;
  const status =
    typeof candidate?.status === "number" ? candidate.status : undefined;
  if (status === 503) {
    return t(
      "knowledge.errPgUnavailable",
      "PG 摄入面暂不可用，请稍后重试或联系管理员",
    );
  }
  if (status === 403) {
    return t("knowledge.errForbidden", "没有该知识库的操作权限");
  }
  if (status === 404) {
    return t("knowledge.errNotFound", "资源不存在或已被删除");
  }

  // Fallback: legacy errors without a structured status still get mapped
  // when the status digits survive in the message text.
  const raw = err instanceof Error ? err.message : String(err);
  if (/\b503\b/.test(raw)) {
    return t(
      "knowledge.errPgUnavailable",
      "PG 摄入面暂不可用，请稍后重试或联系管理员",
    );
  }
  if (/\b403\b/.test(raw)) {
    return t("knowledge.errForbidden", "没有该知识库的操作权限");
  }
  if (/\b404\b/.test(raw)) {
    return t("knowledge.errNotFound", "资源不存在或已被删除");
  }
  return raw;
}
