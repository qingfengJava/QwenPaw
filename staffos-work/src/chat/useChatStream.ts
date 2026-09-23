/**
 * useChatStream — drives one console-chat SSE turn into the timeline model.
 * Owns the send loop, abortable fetch and the remote stop endpoint, keeping
 * Chat.tsx free of protocol details. Send options come from chatPrefs
 * (agent header, approval level, loop-mode prefix) the same way the console
 * reads its agentStore/loopStore globals.
 */
import { useCallback, useRef, useState } from "react";
import { useAuthStore } from "../stores/auth";
import {
  applyLoopModeCommand,
  getSelectedLoopMode,
  useChatPrefs,
} from "../stores/chatPrefs";
import { chatApi } from "../api/modules";
import { streamChat } from "../lib/stream";
import {
  applyEvent,
  userItem,
  type TimelineItem,
  type UserAttachment,
} from "./protocol";

export interface ChatTarget {
  id: string;
  session_id: string;
}

/** Pending composer attachment → wire content block (console contract). */
function attachmentContentItem(a: {
  storedUrl: string;
  name: string;
  type: string;
}): Record<string, unknown> {
  if (a.type.startsWith("image/")) {
    return { type: "image", image_url: a.storedUrl };
  }
  if (a.type.startsWith("video/")) {
    return { type: "video", video_url: a.storedUrl };
  }
  if (a.type.startsWith("audio/")) {
    return { type: "audio", data: a.storedUrl };
  }
  return { type: "file", file_url: a.storedUrl, file_name: a.name };
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

  /**
   * Transform the timeline in place (no abort, no streaming reset) —
   * used by the team-run card live refresh: run SSE events patch the
   * matching team_run item's status/summary while chat streaming may
   * still be running on the same timeline.
   */
  const patch = useCallback(
    (fn: (prev: TimelineItem[]) => TimelineItem[]) => {
      setItems(fn);
    },
    [],
  );

  /** Send one user turn and stream the assistant response. */
  const send = useCallback(
    async (
      text: string,
      target: ChatTarget,
      attachments?: Array<{
        storedUrl: string;
        name: string;
        type: string;
        previewUrl: string;
        uid: string;
        size: number;
      }>,
    ) => {
      const value = text.trim();
      if ((!value && (!attachments || attachments.length === 0)) || !target?.session_id) {
        return;
      }

      // Resolve chat prefs at submit time (agent header / approval / mode).
      const prefs = useChatPrefs.getState();
      const mode = getSelectedLoopMode(prefs.loopModes, prefs.loopModeId);
      const wireText = applyLoopModeCommand(value, mode);

      const displayAttachments: UserAttachment[] = (attachments ?? []).map(
        (a) => ({ name: a.name, type: a.type, url: a.previewUrl }),
      );

      const controller = new AbortController();
      abortRef.current?.abort();
      abortRef.current = controller;
      const myItems = [
        ...itemsRef.current,
        userItem(value, displayAttachments),
      ];
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
                content: [
                  ...(wireText ? [{ type: "text", text: wireText }] : []),
                  ...(attachments ?? []).map(attachmentContentItem),
                ],
              },
            ],
            request_context: {
              approval_level: prefs.approvalLevel,
            },
          },
          (raw) => {
            setItems((prev) => applyEvent(prev, raw));
          },
          prefs.selectedAgent && prefs.selectedAgent !== "default"
            ? { "X-Agent-Id": prefs.selectedAgent }
            : undefined,
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

  return { items, streaming, send, stop, reset, patch };
}
