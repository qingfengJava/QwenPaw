/**
 * shareTask — export one chat as a Markdown file (frontend-only share).
 *
 * The transcript is rebuilt via the same historyToTimeline pipeline the
 * chat page uses (loop-mode prompt stripping, tool-call grouping), then
 * rendered as `## 用户` / `## 助理` sections with tool calls collapsed
 * into fenced code blocks. Zero backend changes: the file downloads via
 * a Blob + a[download] as `任务名.md`.
 */
import { chatApi } from "../api/modules";
import type { ChatSpecView } from "../api/modules";
import { historyToTimeline } from "../chat/protocol";
import type { TimelineItem } from "../chat/protocol";

const MAX_TOOL_OUTPUT = 2000;

function truncate(text: string, max = MAX_TOOL_OUTPUT): string {
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, max)}\n…（输出已截断）`;
}

/** Render one timeline into Markdown sections. */
export function timelineToMarkdown(
  title: string,
  items: TimelineItem[],
): string {
  const lines: string[] = [`# ${title}`, ""];
  for (const item of items) {
    switch (item.kind) {
      case "user": {
        lines.push("## 用户", "");
        if (item.text) {
          lines.push(item.text.trim());
        }
        for (const att of item.attachments ?? []) {
          lines.push(`- 附件：${att.name}`);
        }
        if (!item.text && (item.attachments ?? []).length === 0) {
          lines.push("（媒体消息）");
        }
        lines.push("");
        break;
      }
      case "assistant": {
        lines.push("## 助理", "", (item.text || "").trim(), "");
        break;
      }
      case "tool": {
        lines.push(
          "<details>",
          `<summary>工具调用：${item.name}（${item.status}）</summary>`,
          "",
          "```json",
          truncate(item.args || "{}", 800),
          "```",
          "",
          "```text",
          truncate(item.output || ""),
          "```",
          "",
          "</details>",
          "",
        );
        break;
      }
      case "error": {
        lines.push("## 错误", "", item.text, "");
        break;
      }
      default:
        // reasoning / usage snapshots are internal detail — skipped.
        break;
    }
  }
  return lines.join("\n");
}

function safeFileName(name: string): string {
  const cleaned = (name || "任务").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 60);
  return cleaned || "任务";
}

/** Fetch history, render Markdown, download as `任务名.md`. */
export async function exportChatMarkdown(chat: ChatSpecView): Promise<string> {
  const history = await chatApi.history(chat.id);
  const items = historyToMarkdownSafe(history);
  const markdown = timelineToMarkdown(chat.name || "新任务", items);
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${safeFileName(chat.name)}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return chat.name || "新任务";
}

function historyToMarkdownSafe(
  history: { messages: unknown[]; status?: string },
): TimelineItem[] {
  // historyToTimeline tolerates the raw payload; failures degrade to an
  // empty transcript instead of breaking the download.
  try {
    return historyToTimeline(history);
  } catch {
    return [];
  }
}
