import { getApiUrl, clearAuthToken } from "./config";
import { buildAuthHeaders } from "./authHeaders";
import { getLoginHref, isLoginPath } from "../utils/navigationMode";

function getErrorMessageFromBody(
  text: string,
  contentType: string,
): string | null {
  if (!text) {
    return null;
  }

  if (!contentType.includes("application/json")) {
    return text;
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };

    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message) {
      return payload.message;
    }
    if (typeof payload.error === "string" && payload.error) {
      return payload.error;
    }
  } catch {
    return text;
  }

  return text;
}

function buildHeaders(method?: string, extra?: HeadersInit): Headers {
  // Normalize extra to a Headers instance for consistent handling
  const headers = extra instanceof Headers ? extra : new Headers(extra);

  // Only add Content-Type for methods that typically have a body
  if (method && ["POST", "PUT", "PATCH"].includes(method.toUpperCase())) {
    // Don't override if caller explicitly set Content-Type
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  for (const [key, value] of Object.entries(buildAuthHeaders())) {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  }

  return headers;
}

export interface RequestOptions extends RequestInit {
  /** Request timeout in milliseconds. Defaults to 30000 (30 seconds). */
  timeout?: number;
  /** Number of retry attempts on timeout. Defaults to 0 (no retry). */
  retries?: number;
  /** Delay between retries in milliseconds. Defaults to 1000 (1 second). */
  retryDelay?: number;
}

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_RETRIES = 0;
const DEFAULT_RETRY_DELAY_MS = 1000;

/**
 * 后台配置域越权 403 的 detail 签名（与后端 rbac/deps.py `_deny_manage` 的
 * 固定中文文案对齐）。命中即派发全局事件统一 toast，不在各页面重复处理。
 */
const MANAGE_DENIED_SIGNATURE = "无该员工配置权限";

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = getApiUrl(path);
  const method = options.method || "GET";
  const headers = buildHeaders(method, options.headers);
  const {
    timeout = DEFAULT_TIMEOUT_MS,
    retries = DEFAULT_RETRIES,
    retryDelay = DEFAULT_RETRY_DELAY_MS,
    signal: callerSignal,
    ...fetchOptions
  } = options;

  // Early exit: caller's signal already aborted before we even start
  if (callerSignal?.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    // Create AbortController for timeout handling
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout);

    // Wire caller's signal to our controller so external abort also works
    let onCallerAbort: (() => void) | undefined;
    if (callerSignal) {
      if (callerSignal.aborted) {
        controller.abort();
      } else {
        onCallerAbort = () => controller.abort();
        callerSignal.addEventListener("abort", onCallerAbort, { once: true });
      }
    }

    try {
      const response = await fetch(url, {
        ...fetchOptions,
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          clearAuthToken();
          if (!isLoginPath(window.location.pathname)) {
            window.location.href = getLoginHref(window.location);
          }
          throw new Error("Not authenticated");
        }

        const text = await response.text().catch(() => "");
        const contentType = response.headers.get("content-type") || "";
        const errorMessage = getErrorMessageFromBody(text, contentType);

        // 后台配置域越权（缺员工管理授权）统一 toast：后端 _deny_manage 以固定
        // 中文 detail 返回并要求前端直接展示，这里派发一次全局事件，由挂在
        // antd App 上下文的 GlobalManageDeniedToast 弹一次提示。按 detail 签名
        // 精确匹配，避免干扰其它 403 流程（各页面自有错误处理保持不变）。
        if (
          response.status === 403 &&
          typeof errorMessage === "string" &&
          errorMessage.includes(MANAGE_DENIED_SIGNATURE)
        ) {
          window.dispatchEvent(
            new CustomEvent("qwenpaw:manage-denied", {
              detail: { message: errorMessage, method, path },
            }),
          );
        }

        // Preserve raw body for parseErrorDetail() to extract structured fields
        const finalMessage = errorMessage
          ? `${errorMessage} - ${text}`
          : `Request failed: ${response.status} ${response.statusText}`;

        // Attach the structured status code (non-breaking enhancement): the
        // message text alone may not contain the digits (JSON detail bodies),
        // so callers cannot map 503/403/404 to readable guidance from text.
        const err = new Error(finalMessage);
        (err as Error & { status?: number }).status = response.status;
        throw err;
      }

      if (response.status === 204) {
        return undefined as T;
      }

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        return (await response.text()) as unknown as T;
      }

      return (await response.json()) as T;
    } catch (error) {
      if (
        error instanceof DOMException &&
        error.name === "AbortError" &&
        !timedOut
      ) {
        // External abort (caller cancelled): do not retry, rethrow as-is
        throw error;
      }

      if (error instanceof DOMException && error.name === "AbortError") {
        // Timeout-triggered abort
        lastError = new Error(
          `Request timeout after ${timeout}ms: ${method} ${path}`,
        );

        // Retry if we have attempts remaining
        if (attempt < retries) {
          await new Promise((resolve) => setTimeout(resolve, retryDelay));
          continue;
        }
      } else {
        // Non-timeout errors should not retry
        throw error;
      }
    } finally {
      clearTimeout(timeoutId);
      if (onCallerAbort && callerSignal) {
        callerSignal.removeEventListener("abort", onCallerAbort);
      }
    }
  }

  // All retries exhausted
  throw lastError;
}
