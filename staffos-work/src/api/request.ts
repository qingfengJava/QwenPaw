/**
 * Minimal fetch wrapper for the QwenPaw API (same-origin by default).
 * Mirrors the console `request.ts` contract: bearer token, JSON bodies,
 * 401 → dispatch `xian:unauth` (App.tsx navigates to /login; no absolute
 * location writes so Tauri/ exe packaging stays protocol-safe).
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string {
  return localStorage.getItem("xian_token") ?? "";
}

export function setToken(token: string) {
  localStorage.setItem("xian_token", token);
}

export function clearToken() {
  localStorage.removeItem("xian_token");
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_BASE}/api${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("xian:unauth"));
    throw new ApiError(401, "Not authenticated");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, String(detail));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/** Build auth headers for raw fetches (SSE streams). */
export function authHeaders(extra?: Record<string, string>): HeadersInit {
  const headers: Record<string, string> = {
    ...extra,
  };
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}
