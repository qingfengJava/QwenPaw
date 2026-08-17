/**
 * ShareView — public read-only share page (`/share/:token`).
 *
 * Reached from a share link copied out of the sidebar ShareModal; the page
 * lives outside MainLayout (no login, no sidebar): anyone holding the
 * token sees the chat title, every registered file the conversation
 * produced (downloadable through the public share-file endpoint), and the
 * full transcript rebuilt by the same historyToTimeline pipeline the chat
 * page uses. Rendering is deliberately static — no streaming state, no
 * hover actions.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ShareView as ShareViewData, ShareFileItem } from "../api/modules";
import { shareApi } from "../api/modules";
import { historyToTimeline } from "../chat/protocol";
import type { TimelineItem } from "../chat/protocol";
import MarkdownView from "../components/chat/MarkdownView";

type PageState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: ShareViewData; items: TimelineItem[] };

function formatSize(size: number | null): string {
  if (!size || size <= 0) {
    return "";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function fileIcon(mediaType: string | null, fileName: string | null): string {
  const name = (fileName ?? "").toLowerCase();
  if ((mediaType ?? "").startsWith("image/")) {
    return "fa-regular fa-file-image";
  }
  if (name.endsWith(".pdf")) {
    return "fa-regular fa-file-pdf";
  }
  if (/\.(xlsx?|docx?|pptx?|csv)$/.test(name)) {
    return "fa-regular fa-file-excel";
  }
  if (/\.(zip|rar|7z|tar|gz)$/.test(name)) {
    return "fa-regular fa-file-zipper";
  }
  return "fa-regular fa-file-lines";
}

function FileCard({ file }: { file: ShareFileItem }) {
  const size = formatSize(file.size);
  return (
    <a
      className="share-file-card"
      href={file.url}
      download={file.file_name ?? undefined}
    >
      <i className={fileIcon(file.media_type, file.file_name)} />
      <span className="share-file-name" title={file.file_name ?? ""}>
        {file.file_name ?? file.stored_name}
      </span>
      <span className="share-file-badge">
        {file.source === "agent_output" ? "产出" : "上传"}
      </span>
      {size && <span className="share-file-size">{size}</span>}
      <i className="fa-solid fa-download share-file-download" />
    </a>
  );
}

function TimelineBlock({ item }: { item: TimelineItem }) {
  switch (item.kind) {
    case "user":
      return (
        <div className="share-msg share-msg-user">
          <div className="share-msg-role">用户</div>
          {item.text && <div className="share-msg-text">{item.text}</div>}
          {(item.attachments ?? []).length > 0 && (
            <div className="share-msg-attachments">
              {(item.attachments ?? []).map((att) => (
                <span key={att.url} className="share-att-chip">
                  <i className="fa-solid fa-paperclip" /> {att.name}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    case "assistant":
      return (
        <div className="share-msg share-msg-assistant">
          <div className="share-msg-role">助理</div>
          {item.text ? (
            <MarkdownView text={item.text} />
          ) : (
            <div className="share-msg-text share-msg-empty">（无文本回复）</div>
          )}
        </div>
      );
    case "tool":
      return (
        <details className="share-msg share-msg-tool">
          <summary>
            <i className="fa-solid fa-screwdriver-wrench" />
            {item.name}
            <span className={`share-tool-status ${item.status}`}>
              {item.status}
            </span>
          </summary>
          <pre className="share-tool-output">{item.output || "(无输出)"}</pre>
        </details>
      );
    case "error":
      return <div className="share-msg share-msg-error">{item.text}</div>;
    default:
      // reasoning / usage snapshots are internal detail — skipped.
      return null;
  }
}

export default function ShareView() {
  const { token = "" } = useParams();
  const [state, setState] = useState<PageState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    shareApi
      .view(token)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setState({
          phase: "ready",
          data,
          items: historyToTimeline({ messages: data.messages }),
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : "加载分享失败",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (state.phase === "loading") {
    return (
      <div className="share-page">
        <div className="share-loading">
          <i className="fa-solid fa-spinner fa-spin" /> 正在加载分享…
        </div>
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <div className="share-page">
        <div className="share-error-box">
          <i className="fa-regular fa-face-frown" />
          <p>{state.message}</p>
          <Link className="share-back-link" to="/">
            返回首页
          </Link>
        </div>
      </div>
    );
  }

  const { data, items } = state;
  return (
    <div className="share-page">
      <header className="share-header">
        <div className="share-header-icon">
          <i className="fa-solid fa-comment-dots" />
        </div>
        <div className="share-header-main">
          <h1>{data.chat.name}</h1>
          <p>
            只读分享 · 创建于{" "}
            {new Date(data.chat.created_at).toLocaleString("zh-CN")}
          </p>
        </div>
        <Link className="share-back-link" to="/">
          进入 XianWork
        </Link>
      </header>

      {data.files.length > 0 && (
        <section className="share-files">
          <h2>
            <i className="fa-regular fa-folder-open" /> 会话文件（
            {data.files.length}）
          </h2>
          <div className="share-file-list">
            {data.files.map((f) => (
              <FileCard key={f.stored_name} file={f} />
            ))}
          </div>
        </section>
      )}

      <section className="share-transcript">
        <h2>
          <i className="fa-regular fa-comments" /> 对话记录
        </h2>
        {items.length === 0 ? (
          <div className="share-msg-empty">（暂无对话内容）</div>
        ) : (
          items.map((item) => <TimelineBlock key={item.key} item={item} />)
        )}
      </section>

      <footer className="share-footer">
        由 XianWork 生成分享 · 链接凭 token 访问，无需登录
      </footer>
    </div>
  );
}
