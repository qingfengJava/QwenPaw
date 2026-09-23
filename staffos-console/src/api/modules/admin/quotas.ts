/**
 * admin/quotas.ts — `/admin/quotas` client (M4-4 backend).
 */
import { request } from "../../request";
import type { QuotaRule, QuotaSubjectType, QuotaWindow } from "./types";

export interface QuotaRuleBody {
  subject_type: QuotaSubjectType;
  subject: string;
  model?: string;
  window?: QuotaWindow;
  limit: number;
  description?: string;
}

export interface QuotaKey {
  subject_type: QuotaSubjectType;
  subject: string;
  model: string;
  window: QuotaWindow;
}

export const adminQuotasApi = {
  list: () => request<QuotaRule[]>("/admin/quotas"),

  upsert: (body: QuotaRuleBody) =>
    request<QuotaRule>("/admin/quotas", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  remove: (key: QuotaKey) => {
    const params = new URLSearchParams({
      subject_type: key.subject_type,
      subject: key.subject,
      model: key.model,
      window: key.window,
    });
    return request<void>(`/admin/quotas?${params.toString()}`, {
      method: "DELETE",
    });
  },
};
