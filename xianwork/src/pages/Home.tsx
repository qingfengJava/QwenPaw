/**
 * Home — WorkBuddy-style task launcher: category chips + the big AI
 * input. Sending creates a personal-assistant chat and jumps to it.
 */
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { chatApi } from "../api/modules";
import { authHeaders } from "../api/request";

const CATEGORIES = ["日常办公", "代码开发", "设计创意"];
const ACTIONS = [
  "文档处理",
  "数据分析及可视化",
  "深度研究",
  "个人工作台",
  "幻灯片",
];

/** Stream one console-chat turn (SSE) — shared with the Chat page. */
export async function streamChat(
  path: string,
  body: unknown,
  onEvent: (raw: string) => void,
  extraHeaders?: Record<string, string>,
): Promise<void> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(extraHeaders),
    } as Record<string, string>,
    body: JSON.stringify(body),
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

export default function HomePage() {
  const navigate = useNavigate();
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = async () => {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      const chat = await chatApi.create(value.slice(0, 24));
      // Fire the first turn in the background; the Chat page reconnects
      // to the running stream via its session id.
      streamChat(
        "/console/chat",
        { ...buildAgentRequest(value, chat.id), reconnect: false },
        () => undefined,
      ).catch(() => undefined);
      navigate(`/chat?chat=${chat.id}&kickoff=${encodeURIComponent(value)}`);
    } catch (err) {
      console.error(err);
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        flexGrow: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 40px 80px",
      }}
    >
      <h1 style={{ fontSize: 30, fontWeight: 700, marginBottom: 22 }}>
        XianWork，我帮你
      </h1>

      <div className="xian-chip-row" style={{ maxWidth: 640 }}>
        {CATEGORIES.map((item) => (
          <button
            key={item}
            type="button"
            className={`xian-chip${category === item ? " active" : ""}`}
            onClick={() => setCategory(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="xian-chip-row" style={{ maxWidth: 760 }}>
        {ACTIONS.map((item) => (
          <button
            key={item}
            type="button"
            className="xian-chip"
            onClick={() => {
              setText(`${item}：`);
              inputRef.current?.focus();
            }}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="xian-input-bar">
        <textarea
          ref={inputRef}
          placeholder="今天帮你做些什么？（@ 引用会话文件，/ 调用技能与指令）"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginTop: 10,
            gap: 12,
          }}
        >
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            个人助手 · 默认权限
          </span>
          <button
            type="button"
            onClick={handleSend}
            disabled={busy || !text.trim()}
            style={{
              width: 32,
              height: 32,
              borderRadius: "50%",
              border: "none",
              cursor: text.trim() ? "pointer" : "default",
              background: text.trim() ? "#2b2d31" : "#d1d1d6",
              color: "#fff",
            }}
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  );
}
