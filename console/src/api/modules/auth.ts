import { getApiUrl } from "../config";
import { responseErrorMessage } from "../error";

export interface LoginResponse {
  token: string;
  username: string;
  message?: string;
}

export interface AuthStatusResponse {
  enabled: boolean;
  has_users: boolean;
  /** M6: "hub" when served by the self-hosted Hub control plane. */
  mode?: "hub";
  bootstrap_required?: boolean;
  registration_enabled?: boolean;
  /** 默认超管仍使用内置默认口令时 true，登录页提示尽快修改。 */
  default_admin_hint?: boolean;
}

/**
 * Phase 4: minimal organization record exposed by the public
 * `GET /auth/orgs` endpoint. Only fields safe to reveal before login
 * are included; sensitive attributes (settings / plan / status) stay
 * server-side.
 */
export interface OrgInfo {
  id: string;
  name: string;
  slug: string;
}

/**
 * Response of `GET /auth/verify`. The role fields arrived with M5; older
 * backends omit them, so consumers must tolerate their absence (treated as
 * "unknown", i.e. non-admin display filtering).
 */
export interface VerifyResponse {
  valid: boolean;
  username: string;
  /** M1 flat role ("admin" | "employee" | ""). */
  role?: string;
  /** M4 RBAC role names (e.g. "platform_admin"). */
  roles?: string[];
}

export const authApi = {
  login: async (
    username: string,
    password: string,
    rememberMe = false,
  ): Promise<LoginResponse> => {
    // Phase 4: "记住我" = permanent token (expires_in = -1 → 100 years)
    // vs default 7 days. Backend `LoginRequest.expires_in` already
    // supports this; nothing new server-side.
    const body: Record<string, unknown> = { username, password };
    if (rememberMe) {
      body.expires_in = -1;
    }
    const res = await fetch(getApiUrl("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(await responseErrorMessage(res, "Login failed"));
    }
    return res.json();
  },

  register: async (
    username: string,
    password: string,
    orgId?: string,
  ): Promise<LoginResponse> => {
    const body: Record<string, unknown> = { username, password };
    if (orgId) {
      body.org_id = orgId;
    }
    const res = await fetch(getApiUrl("/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(await responseErrorMessage(res, "Registration failed"));
    }
    return res.json();
  },

  /**
   * Phase 4: fetch organizations selectable at registration. Public
   * endpoint — no auth required. Returns an empty list when the orgs
   * service is unavailable (single-tenant / non-enterprise deployment).
   */
  getOrgs: async (): Promise<OrgInfo[]> => {
    const res = await fetch(getApiUrl("/auth/orgs"));
    if (!res.ok) {
      // Degrade gracefully: the registration form hides the org select
      // when the list is empty, matching the non-enterprise default.
      return [];
    }
    const data = await res.json();
    return Array.isArray(data) ? (data as OrgInfo[]) : [];
  },

  getStatus: async (): Promise<AuthStatusResponse> => {
    const res = await fetch(getApiUrl("/auth/status"));
    if (!res.ok) throw new Error("Failed to check auth status");
    return res.json();
  },

  verify: async (token: string): Promise<VerifyResponse> => {
    const res = await fetch(getApiUrl("/auth/verify"), {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Token verification failed");
    }
    return res.json();
  },

  updateProfile: async (
    currentPassword: string,
    newUsername?: string,
    newPassword?: string,
    displayName?: string,
  ): Promise<LoginResponse> => {
    const token = localStorage.getItem("qwenpaw_auth_token") || "";
    const res = await fetch(getApiUrl("/auth/update-profile"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_username: newUsername || null,
        new_password: newPassword || null,
        // 昵称为展示型资料：传值即更新；仅改昵称时后端返回空 token（不登出）。
        display_name:
          displayName === undefined ? null : displayName.trim() || "",
      }),
    });
    if (!res.ok) {
      throw new Error(await responseErrorMessage(res, "Update failed"));
    }
    return res.json();
  },
};
