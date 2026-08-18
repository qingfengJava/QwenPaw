/**
 * GET-based SSE subscription for the project feed
 * (`GET /api/xian/projects/{id}/events`, see backend routers/xian/feed.py).
 *
 * Native EventSource cannot send the Authorization header, so this uses
 * fetch + reader with manual `id:`/`data:` frame parsing, Last-Event-ID
 * resume and exponential-backoff reconnect (1s → 30s cap). The backend
 * sends a 25s keepalive and replays up to 256 buffered events per
 * subscriber, so a reconnect generally loses nothing.
 */
import { authHeaders } from "../api/request";

export interface FeedStreamHandlers {
  /** Called once per parsed SSE event (data payload already trimmed). */
  onEvent: (data: string, id: number | null) => void;
  /** Called when the stream drops and a reconnect is scheduled. */
  onReconnect?: (attempt: number, delayMs: number) => void;
}

export interface FeedStreamHandle {
  close: () => void;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export function subscribeFeed(
  projectId: string,
  handlers: FeedStreamHandlers,
): FeedStreamHandle {
  return subscribeSse(
    `/api/xian/projects/${encodeURIComponent(projectId)}/events`,
    handlers,
  );
}

/**
 * Run-detail SSE subscription (`GET /api/xian/workforce/runs/{id}/events`).
 * Same frame parsing / resume / backoff as the project feed — the backend
 * endpoint is the identical Last-Event-ID + keepalive shape.
 */
export function subscribeRunEvents(
  runId: string,
  handlers: FeedStreamHandlers,
): FeedStreamHandle {
  return subscribeSse(
    `/api/xian/workforce/runs/${encodeURIComponent(runId)}/events`,
    handlers,
  );
}

/** Generic GET-SSE subscription shared by the project feed and run events. */
function subscribeSse(
  path: string,
  handlers: FeedStreamHandlers,
): FeedStreamHandle {
  const controller = new AbortController();
  let lastEventId: number | null = null;
  let attempt = 0;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const parseFrame = (frame: string) => {
    let data = "";
    let id: number | null = null;
    for (const line of frame.split("\n")) {
      if (line.startsWith("data:")) {
        data += (data ? "\n" : "") + line.slice(5).trim();
      } else if (line.startsWith("id:")) {
        const parsed = Number(line.slice(3).trim());
        if (Number.isFinite(parsed)) {
          id = parsed;
        }
      }
    }
    if (id !== null) {
      lastEventId = id;
    }
    if (data) {
      handlers.onEvent(data, id);
    }
  };

  const run = async () => {
    while (!closed) {
      try {
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          ...authHeaders(),
        } as Record<string, string>;
        if (lastEventId !== null) {
          headers["Last-Event-ID"] = String(lastEventId);
        }
        const res = await fetch(path, {
          headers,
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          throw new Error(`sse stream failed: ${res.status}`);
        }
        attempt = 0;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            parseFrame(part);
          }
        }
        // Stream ended cleanly (server shutdown) — reconnect.
        throw new Error("sse stream ended");
      } catch (err) {
        if (closed || controller.signal.aborted) {
          return;
        }
        attempt += 1;
        const delay = Math.min(
          BASE_BACKOFF_MS * 2 ** (attempt - 1),
          MAX_BACKOFF_MS,
        );
        handlers.onReconnect?.(attempt, delay);
        await new Promise<void>((resolve) => {
          timer = setTimeout(resolve, delay);
        });
        timer = null;
      }
    }
  };

  void run();

  return {
    close: () => {
      closed = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      controller.abort();
    },
  };
}
