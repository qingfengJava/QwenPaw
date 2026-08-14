/**
 * ToolCallCard — generic tool invocation card covering the backend's 30+
 * specialized cards with one expandable shape: icon + localized verb +
 * running/completed state + collapsible arguments & output. Specialized
 * cards can be layered in later iterations without touching call sites.
 */
import { useState } from "react";

const TOOL_META: Record<string, { icon: string; label: string }> = {
  execute_shell_command: { icon: "fa-terminal", label: "执行命令" },
  shell_command: { icon: "fa-terminal", label: "执行命令" },
  read_file: { icon: "fa-file-lines", label: "读取文件" },
  write_file: { icon: "fa-file-pen", label: "写入文件" },
  edit_file: { icon: "fa-pen-to-square", label: "编辑文件" },
  glob_search: { icon: "fa-magnifying-glass", label: "搜索文件名" },
  grep_search: { icon: "fa-magnifying-glass-plus", label: "搜索内容" },
  browser_use: { icon: "fa-globe", label: "浏览网页" },
  web_search: { icon: "fa-globe", label: "联网搜索" },
  memory_search: { icon: "fa-brain", label: "检索记忆" },
  send_file: { icon: "fa-paper-plane", label: "发送文件" },
  view_image: { icon: "fa-image", label: "查看图片" },
  get_current_time: { icon: "fa-clock", label: "获取时间" },
  list_agents: { icon: "fa-users", label: "列出 Agent" },
  chat_with_agent: { icon: "fa-comments", label: "咨询专家" },
  token_usage: { icon: "fa-coins", label: "用量统计" },
};

function prettyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export interface ToolCallCardProps {
  name: string;
  args: string;
  output: string;
  status: "running" | "completed" | "error";
}

export default function ToolCallCard({ name, args, output, status }: ToolCallCardProps) {
  const meta = TOOL_META[name] ?? { icon: "fa-screwdriver-wrench", label: name };
  const hasDetail = Boolean(args || output);
  const [open, setOpen] = useState(false);

  return (
    <div className={`tool-card status-${status}`}>
      <button
        type="button"
        className="tool-card-header"
        onClick={() => hasDetail && setOpen((v) => !v)}
        disabled={!hasDetail}
      >
        <span className="tool-card-icon">
          <i className={`fa-solid ${meta.icon}`} />
        </span>
        <span className="tool-card-label">{meta.label}</span>
        {status === "running" && <i className="fa-solid fa-spinner fa-spin tool-card-state" />}
        {status === "completed" && <i className="fa-solid fa-check tool-card-state ok" />}
        {status === "error" && <i className="fa-solid fa-xmark tool-card-state bad" />}
        {hasDetail && <i className={`fa-solid fa-chevron-${open ? "up" : "down"} tool-card-caret`} />}
      </button>
      {open && (
        <div className="tool-card-detail">
          {args && (
            <>
              <div className="tool-card-section">参数</div>
              <pre className="tool-card-pre">{prettyJson(args)}</pre>
            </>
          )}
          {output && (
            <>
              <div className="tool-card-section">结果</div>
              <pre className="tool-card-pre">{output}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
