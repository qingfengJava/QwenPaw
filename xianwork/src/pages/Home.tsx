/**
 * Home — prototype home view (L1084-1140): top points bar, 32px title,
 * category tabs, action chips, and the shared PromptInput launcher.
 * Sending creates a personal-assistant chat and jumps to it (logic
 * preserved from the scaffold; stream helpers moved to lib/stream.ts).
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PromptInput from "../components/PromptInput";
import AgentSelector from "../components/chat/AgentSelector";
import ApprovalSelector from "../components/chat/ApprovalSelector";
import LoopModeSelector from "../components/chat/LoopModeSelector";
import { chatApi } from "../api/modules";
import { useAuthStore } from "../stores/auth";

const CATEGORIES = [
  { label: "日常办公", icon: "fa-solid fa-mug-hot" },
  { label: "代码开发", icon: "fa-solid fa-code" },
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

  const handleSend = async (value: string) => {
    if (busy) return;
    setBusy(true);
    try {
      // Create the chat, then hand the text to the Chat page as kickoff —
      // it performs the real streamed send once history is loaded. No
      // background pre-send (that desynced the visible conversation).
      const chat = await chatApi.create(value.slice(0, 24) || "新对话", username);
      navigate(`/chat?chat=${chat.id}&kickoff=${encodeURIComponent(value)}`);
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

        <PromptInput
          variant="home"
          placeholder="今天帮你做些什么？ @ 引用对话文件，/ 调用技能与指令"
          value={text}
          onChange={setText}
          onSend={(value) => void handleSend(value)}
          busy={busy}
        />

        {/* Real chat prefs — same store the Chat composer uses, so choices
            made here carry into the conversation after navigation. */}
        <div className="home-chat-prefs">
          <LoopModeSelector />
          <ApprovalSelector />
          <AgentSelector />
        </div>
      </div>
    </div>
  );
}
