/**
 * WorkbenchChatPanel — 工作台左栏固定聊天面板。
 *
 * 直接复用 @/pages/Chat（eager）。注意：Chat 切换会话时会硬导航
 * `/chat/<sessionId>`（见 utils/sessionRoute），因此本面板**不再自挂
 * MemoryRouter** —— React Router 禁止 Router 嵌套；会话沙箱由
 * AgentWorkbenchLayout 在外层统一提供（同 /studio 顶层的 /chat/* 路由）。
 *
 * 面板宽度可拖拽、可折叠为 44px 窄条，均持久化到 localStorage。
 */
import { useCallback, useEffect, useRef } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import Chat from "@/pages/Chat";
import styles from "./workbench.module.less";

const WIDTH_KEY = "qwenpaw-workbench-chat-width";
const COLLAPSED_KEY = "qwenpaw-workbench-chat-collapsed";

const WIDTH_MIN = 360;
/** 右侧信息区保留的最小宽度。 */
const RIGHT_MIN = 420;

export const DEFAULT_CHAT_WIDTH = 480;

export function loadChatWidth(): number {
  const raw = Number(localStorage.getItem(WIDTH_KEY));
  return Number.isFinite(raw) && raw >= WIDTH_MIN ? raw : DEFAULT_CHAT_WIDTH;
}

export function saveChatWidth(width: number): void {
  try {
    localStorage.setItem(WIDTH_KEY, String(width));
  } catch {
    /* ignore */
  }
}

export function loadChatCollapsed(): boolean {
  return localStorage.getItem(COLLAPSED_KEY) === "1";
}

export function saveChatCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
}

interface WorkbenchChatPanelProps {
  width: number;
  collapsed: boolean;
  /** 调试模式：会话跑在草稿实例上，面板以琥珀色顶边 + 徽标提示。 */
  debugOn: boolean;
  /** 变更时强制重挂 Chat（消费 stash 的 AI 调优预填指令）。 */
  chatKey?: number;
  /** 隐藏聊天头部模型选择器（默认模型配置入口在档案区）。 */
  hideHeaderModelSelector?: boolean;
  onWidthChange: (width: number) => void;
  onCollapsedChange: (collapsed: boolean) => void;
}

export default function WorkbenchChatPanel({
  width,
  collapsed,
  debugOn,
  chatKey,
  hideHeaderModelSelector = false,
  onWidthChange,
  onCollapsedChange,
}: WorkbenchChatPanelProps) {
  const { t } = useTranslation();
  const draggingRef = useRef(false);
  const lastWidthRef = useRef(width);
  lastWidthRef.current = width;

  // 拖拽调宽：以视口右缘反推宽度（面板贴左，右侧为信息区）。
  const onResizeStart = useCallback(
    (e: ReactMouseEvent) => {
      e.preventDefault();
      draggingRef.current = true;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const onMove = (ev: MouseEvent) => {
        if (!draggingRef.current) return;
        const max = window.innerWidth - RIGHT_MIN;
        const next = Math.min(max, Math.max(WIDTH_MIN, window.innerWidth - ev.clientX));
        lastWidthRef.current = next;
        onWidthChange(next);
      };
      const onUp = () => {
        draggingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        // 拖拽中只更新内存态，mouseup 收口时一次性持久化。
        saveChatWidth(lastWidthRef.current);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [onWidthChange],
  );

  // 拖拽中宽度实时写入持久层由 onUp 收口；这里同步响应折叠态。
  useEffect(() => {
    saveChatCollapsed(collapsed);
  }, [collapsed]);

  if (collapsed) {
    return (
      <aside
        className={`${styles.chatPanel} ${styles.chatRail}`}
        style={{ width: 44 }}
      >
        <button
          type="button"
          className={styles.headerBtn}
          title={t("workbench.expandChat", "展开对话")}
          onClick={() => onCollapsedChange(false)}
        >
          <PanelLeftOpen size={16} />
        </button>
        {debugOn ? <span className={`${styles.modeDot} ${styles.modeDotDebug}`} /> : null}
      </aside>
    );
  }

  return (
    <aside
      className={`${styles.chatPanel} ${debugOn ? styles.chatPanelDebug : ""}`}
      style={{ width }}
    >
      <div className={styles.chatPanelHeader}>
        <span className={styles.modeBadge}>
          <span
            className={`${styles.modeDot} ${debugOn ? styles.modeDotDebug : ""}`}
          />
          {debugOn
            ? t("workbench.modeDraft", "调试草稿")
            : t("workbench.modeLive", "线上版本")}
        </span>
        <span className={styles.headerSpacer} />
        <button
          type="button"
          className={styles.headerBtn}
          title={t("workbench.collapseChat", "折叠对话")}
          onClick={() => onCollapsedChange(true)}
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className={styles.chatHost}>
        {/* hideWorkspaceToggle：右侧能力 Tab 已有知识库入口，隐藏头部工作区按钮 */}
        <Chat
          key={chatKey ?? 0}
          hideHeaderModelSelector={hideHeaderModelSelector}
          hideWorkspaceToggle
        />
      </div>

      <div
        className={styles.resizeHandle}
        onMouseDown={onResizeStart}
        role="separator"
        aria-orientation="vertical"
      />
    </aside>
  );
}
