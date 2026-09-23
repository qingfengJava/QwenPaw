/**
 * Streaming helpers shared by Home / Chat / Experts / ProjectDetail.
 * Moved verbatim from pages/Home.tsx (pure relocation, no logic change).
 */
import { authHeaders } from "../api/request";

/** Stream one console-chat turn (SSE) — POST + reader based. */
export async function streamChat(
  path: string,
  body: unknown,
  onEvent: (raw: string) => void,
  extraHeaders?: Record<string, string>,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(extraHeaders),
    } as Record<string, string>,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`chat failed: ${res.status}`);
  }
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
      for (const line of part.split("\n")) {
        if (line.startsWith("data:")) {
          onEvent(line.slice(5).trim());
        }
      }
    }
  }
}

export function buildAgentRequest(text: string, sessionId: string) {
  return {
    channel: "console",
    user_id: "local",
    session_id: sessionId,
    input: [
      {
        role: "user",
        content: [{ type: "text", text }],
      },
    ],
  };
}
