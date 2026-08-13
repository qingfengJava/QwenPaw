import { getApiUrl } from "../config";

export interface LoginResponse {
  token: string;
  username: string;
  message?: string;
}

export interface AuthStatusResponse {
  enabled: boolean;
  has_users: boolean;
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
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    return res.json();
  },

  register: async (
    username: string,
    password: string,
  ): Promise<LoginResponse> => {
    const res = await fetch(getApiUrl("/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Registration failed");
    }
    return res.json();
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
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Update failed");
    }
    return res.json();
  },
};
