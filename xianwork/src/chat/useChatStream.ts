/**
 * useChatStream — drives one console-chat SSE turn into the timeline model.
 * Owns the send loop, abortable fetch and the remote stop endpoint, keeping
 * Chat.tsx free of protocol details.
 */
import { useCallback, useRef, useState } from "react";
import { useAuthStore } from "../stores/auth";
import { chatApi } from "../api/modules";
import { streamChat } from "../lib/stream";
import { applyEvent, userItem, type TimelineItem } from "./protocol";

export interface ChatTarget {
  id: string;
  session_id: string;
}

export function useChatStream() {
  const username = useAuthStore((s) => s.username);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /** Replace the whole timeline (history load / session switch). */
  const reset = useCallback((next: TimelineItem[]) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setItems(next);
  }, []);

  /** Send one user turn and stream the assistant response. */
  const send = useCallback(
    async (text: string, target: ChatTarget) => {
      const value = text.trim();
      if (!value || !target?.session_id) {
        return;
      }

      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;
      const myItems = [...itemsRef.current, userItem(value)];
      setItems(myItems);
      setStreaming(true);

      try {
        await streamChat(
          "/console/chat",
          {
            channel: "console",
            user_id: username || "local",
            session_id: target.session_id,
            input: [
              {
                role: "user",
                content: [{ type: "text", text: value }],
              },
            ],
          },
          (raw) => {
            setItems((prev) => applyEvent(prev, raw));
          },
          undefined,
          controller.signal,
        );
      } catch (err) {
        if (!controller.signal.aborted) {
          setItems((prev) => [
            ...prev,
            {
              kind: "error",
              key: `err_${Date.now()}`,
              text: `连接中断：${err instanceof Error ? err.message : String(err)}`,
            },
          ]);
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setStreaming(false);
        }
      }
    },
    [username],
  );

  /**
   * Stop the running turn: abort the local stream and ask the backend to
   * cancel the agent run so tokens stop burning. When nothing had streamed
   * back yet, surface a "stopped" marker so the turn isn't left silent.
   */
  const stop = useCallback(
    async (target: ChatTarget) => {
      abortRef.current?.abort();
      abortRef.current = null;
      setStreaming(false);
      setItems((prev) => {
        const last = prev[prev.length - 1];
        const hasAnswer =
          last &&
          (last.kind === "assistant" ||
            last.kind === "tool" ||
            last.kind === "usage" ||
            (last.kind === "reasoning" && prev.some((it) => it.kind === "assistant")));
        if (hasAnswer) {
          return prev;
        }
        return [
          ...prev,
          { kind: "error", key: `stopped_${Date.now()}`, text: "已停止生成" },
        ];
      });
      if (target?.id) {
        try {
          await chatApi.stop(target.id);
        } catch {
          // Backend may have already finished the turn — ignore stop errors.
        }
      }
    },
    [],
  );

  // Keep a ref mirror so send() always appends to the freshest timeline
  // without re-creating the callback on every streaming frame.
  const itemsRef = useRef<TimelineItem[]>([]);
  itemsRef.current = items;

  return { items, streaming, send, stop, reset };
}
