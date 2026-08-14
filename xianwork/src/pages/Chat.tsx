/**
 * Chat — personal assistant conversations over the console SSE plane.
 * Extension design: chat list rail + bubble stream + the shared
 * PromptInput (detail variant) docked at the bottom. Streaming logic
 * preserved from the scaffold (helpers now in lib/stream.ts).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import PromptInput from "../components/PromptInput";
import { chatApi } from "../api/modules";
import type { ChatSpecView } from "../api/modules";
import { buildAgentRequest, streamChat } from "../lib/stream";

interface Bubble {
  role: "user" | "assistant";
  text: string;
}

export default function ChatPage() {
  const navigate = useNavigate();
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
    setBubbles((prev) => [...prev, { role: "user", text: value }]);
    setStreaming(true);
    setBubbles((prev) => [...prev, { role: "assistant", text: "" }]);
    try {
      await streamChat(
        "/console/chat",
        buildAgentRequest(value, activeId || "default"),
        (raw: string) => {
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
    <div className="view active" style={{ flexDirection: "row" }}>
      {/* chat list rail */}
      <div
        style={{
          width: 240,
          borderRight: "1px solid var(--border-light)",
          padding: 14,
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontWeight: 600,
            fontSize: 12,
            color: "var(--text-muted)",
            marginBottom: 10,
            padding: "0 4px",
          }}
        >
          任务会话
        </div>
        {chats.map((chat) => (
          <div
            key={chat.id}
            className={`nav-item${chat.id === activeId ? " active" : ""}`}
            onClick={() => navigate(`/chat?chat=${chat.id}`)}
          >
            <div className="nav-item-left">
              <span>{chat.name}</span>
            </div>
          </div>
        ))}
      </div>

      {/* conversation */}
      <div
        style={{
          flexGrow: 1,
          display: "flex",
          flexDirection: "column",
          position: "relative",
          minWidth: 0,
        }}
      >
        <div className="chat-scroll">
          <div style={{ maxWidth: 820, width: "100%", margin: "0 auto" }}>
            {bubbles.length === 0 && (
              <div className="blank-state" style={{ marginTop: 80 }}>
                <i
                  className="fa-regular fa-comment-dots"
                  style={{ fontSize: 26, marginBottom: 10 }}
                />
                <div>和你的个人助手聊点什么吧</div>
              </div>
            )}
            {bubbles.map((bubble, index) => (
              <div
                key={index}
                className={`chat-message ${bubble.role}`}
              >
                {bubble.role === "assistant" && (
                  <div className="chat-sender">XianWork 助理</div>
                )}
                <div
                  className="chat-bubble"
                  style={{ maxWidth: "78%" }}
                >
                  {bubble.text ||
                    (streaming && index === bubbles.length - 1 ? "▍" : "")}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="fixed-bottom-input">
          <PromptInput
            variant="detail"
            placeholder="发送消息给个人助手…"
            value={input}
            onChange={setInput}
            onSend={(value) => void send(value)}
            busy={streaming}
            contextTags={[{ label: "本地任务" }]}
          />
        </div>
      </div>
    </div>
  );
}
