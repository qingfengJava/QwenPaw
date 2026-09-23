/**
 * Home — prototype home view (L1084-1140): top points bar, 32px title,
 * category tabs, action chips, and the full ChatComposer launcher. Sending
 * creates a personal-assistant chat, hands text + attachments to the Chat
 * page via kickoff params + sessionStorage, and jumps to it.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ChatComposer, {
  type PendingAttachment,
} from "../components/chat/ChatComposer";
import { chatApi } from "../api/modules";
import { useAuthStore } from "../stores/auth";
import { useChatsStore } from "../stores/chats";

/** SessionStorage bridge for kickoff attachments (cleared by Chat on read). */
export const KICKOFF_ATTACHMENTS_KEY = "xianwork_kickoff_attachments";

const CATEGORIES = [
  { label: "日常办公", icon: "fa-solid fa-mug-hot" },
  { label: "设计创意", icon: "fa-solid fa-palette" },
];

const ACTIONS = [
  { label: "文档处理", icon: "fa-regular fa-file-word" },
  { label: "金融服务", icon: "fa-solid fa-briefcase" },
  { label: "数据分析及可视化", icon: "fa-solid fa-chart-pie" },
  { label: "个人工作台", icon: "fa-solid fa-table-cells-large" },
  { label: "幻灯片", icon: "fa-solid fa-desktop" },
  { label: "深度研究", icon: "fa-solid fa-magnifying-glass-chart" },
  { label: "视频生成", icon: "fa-solid fa-video" },
];

export default function HomePage() {
  const navigate = useNavigate();
  const username = useAuthStore((s) => s.username);
  const [category, setCategory] = useState(CATEGORIES[0].label);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);

  const handleSend = async (value: string, pending: PendingAttachment[]) => {
    if (busy) return;
    if (!value.trim() && pending.length === 0) return;
    setBusy(true);
    try {
      // Create the chat, then hand text + attachments to the Chat page as
      // kickoff — it performs the real streamed send once history loads.
      const chat = await chatApi.create(value.slice(0, 24) || "新对话", username);
      // Apply the launcher's workspace pick through the shared store
      // helper (clear-first, best-effort — see applyPendingWorkspace).
      await useChatsStore.getState().applyPendingWorkspace(chat.id);
      await useChatsStore.getState().reload();
      if (pending.length > 0) {
        try {
          sessionStorage.setItem(
            KICKOFF_ATTACHMENTS_KEY,
            JSON.stringify(pending),
          );
        } catch {
          // non-fatal: kickoff text still goes through
        }
      }
      navigate(
        `/chat?chat=${chat.id}&kickoff=${encodeURIComponent(value)}`,
      );
    } catch (err) {
      console.error(err);
      setBusy(false);
    }
  };

  return (
    <div className="view active home-view">
      <div className="home-top-bar">
        <button
          type="button"
          className="points-btn"
          title="做任务赢积分好礼"
        >
          <i className="fa-solid fa-gift" style={{ color: "#10a37f" }} />
          做任务赢积分好礼{" "}
          <i
            className="fa-solid fa-chevron-right"
            style={{ fontSize: 10, marginLeft: 2 }}
          />
        </button>
      </div>

      <div className="home-center-content">
        <h1 className="main-title">XianWork, 我帮你</h1>

        <div className="category-tabs">
          {CATEGORIES.map((item) => (
            <button
              key={item.label}
              type="button"
              className={`category-tab${category === item.label ? " active" : ""}`}
              onClick={() => setCategory(item.label)}
            >
              <i className={item.icon} style={{ marginRight: 6 }} />
              {item.label}
            </button>
          ))}
        </div>

        <div className="action-chips">
          {ACTIONS.map((item) => (
            <button
              key={item.label}
              type="button"
              className="action-chip"
              onClick={() => setText(`${item.label}：`)}
            >
              <i className={item.icon} />
              {item.label}
            </button>
          ))}
        </div>

        <ChatComposer
          value={text}
          onChange={setText}
          onSend={(value, pending) => void handleSend(value, pending)}
          busy={busy}
          attachments={attachments}
          onAttachmentsChange={setAttachments}
          placeholder="今天帮你做些什么？ @ 引用对话文件，/ 调用技能与指令"
        />
      </div>
    </div>
  );
}
