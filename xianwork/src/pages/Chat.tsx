/**
 * Chat — personal assistant conversations over the console SSE plane.
 * The left column lists the caller's chats (owner-isolated M1); the
 * main area streams assistant replies incrementally.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { chatApi } from "../api/modules";
import type { ChatSpecView } from "../api/modules";
import { buildAgentRequest, streamChat } from "./Home";

interface Bubble {
  role: "user" | "assistant";
  text: string;
}

export default function ChatPage() {
  const [params] = useSearchParams();
  const activeId = params.get("chat") ?? "";
  const kickoff = params.get("kickoff") ?? "";

  const [chats, setChats] = useState<ChatSpecView[]>([]);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadChats = useCallback(async () => {
    try {
      setChats(await chatApi.list());
    } catch {
      setChats([]);
    }
  }, []);

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  useEffect(() => {
    if (kickoff && activeId) {
      setBubbles([{ role: "user", text: kickoff }]);
    }
  }, [kickoff, activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bubbles]);

  const send = async (text: string) => {
    const value = text.trim();
    if (!value || streaming) return;
    setInput("");
    setBubbles((prev) => [...prev, { role: "user", text: value }]);
    setStreaming(true);
    setBubbles((prev) => [...prev, { role: "assistant", text: "" }]);
    try {
      await streamChat(
        "/console/chat",
        buildAgentRequest(value, activeId || "default"),
        (raw) => {
          try {
            const evt = JSON.parse(raw);
            const delta =
              evt?.choices?.[0]?.delta?.content ??
              evt?.delta ??
              evt?.content ??
              (typeof evt?.text === "string" ? evt.text : "");
            if (delta) {
              setBubbles((prev) => {
                const copy = [...prev];
                const last = copy[copy.length - 1];
                if (last && last.role === "assistant") {
                  copy[copy.length - 1] = { ...last, text: last.text + delta };
                }
                return copy;
              });
            }
          } catch {
            /* non-JSON keepalive/comment lines */
          }
        },
      );
    } catch (err) {
      setBubbles((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", text: `（连接中断：${String(err)}）` },
      ]);
    } finally {
      setStreaming(false);
      loadChats();
    }
  };

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <div
        style={{
          width: 260,
          borderRight: "1px solid var(--border-light)",
          padding: 14,
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontWeight: 600,
            fontSize: 13,
            color: "var(--text-muted)",
            marginBottom: 10,
          }}
        >
          任务会话
        </div>
        {chats.map((chat) => (
          <div
            key={chat.id}
            onClick={() =>
              window.location.assign(
                `/xianwork/chat?chat=${chat.id}`,
              )
            }
            style={{
              padding: "9px 10px",
              borderRadius: 8,
              cursor: "pointer",
              fontSize: 13,
              marginBottom: 2,
              background:
                chat.id === activeId ? "var(--bg-sidebar-active)" : "transparent",
            }}
          >
            {chat.name}
          </div>
        ))}
      </div>

      <div
        style={{
          flexGrow: 1,
          display: "flex",
          flexDirection: "column",
          padding: "24px 28px",
          overflowY: "auto",
        }}
      >
        <div style={{ maxWidth: 820, width: "100%", margin: "0 auto" }}>
          {bubbles.length === 0 && (
            <div
              style={{
                textAlign: "center",
                color: "var(--text-muted)",
                marginTop: 120,
              }}
            >
              和你的个人助手聊点什么吧
            </div>
          )}
          {bubbles.map((bubble, index) => (
            <div
              key={index}
              style={{
                display: "flex",
                justifyContent:
                  bubble.role === "user" ? "flex-end" : "flex-start",
                marginBottom: 14,
              }}
            >
              <div
                style={{
                  maxWidth: "78%",
                  padding: "10px 14px",
                  borderRadius: 12,
                  background:
                    bubble.role === "user" ? "#3b6ef6" : "#f4f4f5",
                  color: bubble.role === "user" ? "#fff" : "inherit",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.6,
                  fontSize: 14,
                }}
              >
                {bubble.text ||
                  (streaming && index === bubbles.length - 1
                    ? "▍"
                    : "")}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div style={{ flexGrow: 1 }} />

        <div className="xian-input-bar" style={{ margin: "0 auto", maxWidth: 820 }}>
          <textarea
            placeholder="发送消息给个人助手…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              marginTop: 8,
            }}
          >
            <button
              type="button"
              onClick={() => send(input)}
              disabled={streaming || !input.trim()}
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                border: "none",
                background: input.trim() ? "#2b2d31" : "#d1d1d6",
                color: "#fff",
                cursor: input.trim() ? "pointer" : "default",
              }}
            >
              ➤
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
