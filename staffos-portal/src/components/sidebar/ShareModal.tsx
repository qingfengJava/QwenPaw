/**
 * ShareModal — 分享任务 dialog: capability link first, export second.
 *
 * Opening the modal mints (or reuses) the backend share link for the chat
 * (POST /api/xian/shares) and shows the absolute URL with a copy button —
 * the link opens the public read-only share page in any browser, no login
 * needed. A secondary action keeps the original Markdown file export for
 * offline archiving.
 */
import { useEffect, useState } from "react";
import type { ChatSpecView } from "../../api/modules";
import { shareApi } from "../../api/modules";
import { exportChatMarkdown } from "../../lib/shareTask";
import { useToast } from "../Toast";
import Modal from "../Modal";

export interface ShareModalProps {
  open: boolean;
  chat: ChatSpecView | null;
  onClose: () => void;
}

type LinkState =
  | { phase: "loading" }
  | { phase: "ready"; url: string }
  | { phase: "error"; message: string };

export default function ShareModal({ open, chat, onClose }: ShareModalProps) {
  const toast = useToast();
  const [link, setLink] = useState<LinkState>({ phase: "loading" });
  const [exporting, setExporting] = useState(false);

  // Mint/reuse the share link every time the dialog opens for a chat.
  useEffect(() => {
    if (!open || !chat) {
      return;
    }
    let cancelled = false;
    setLink({ phase: "loading" });
    shareApi
      .create(chat.id)
      .then((r) => {
        if (!cancelled) {
          setLink({ phase: "ready", url: `${window.location.origin}${r.url}` });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLink({
            phase: "error",
            message: err instanceof Error ? err.message : "生成链接失败",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, chat]);

  const copyLink = async () => {
    if (link.phase !== "ready") {
      return;
    }
    try {
      await navigator.clipboard.writeText(link.url);
      toast.success("链接已复制");
    } catch {
      toast.error("复制失败，请手动选择复制");
    }
  };

  const exportFile = async () => {
    if (!chat || exporting) {
      return;
    }
    setExporting(true);
    try {
      const name = await exportChatMarkdown(chat);
      toast.success(`已导出「${name}.md」`);
    } catch {
      toast.error("导出失败");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="分享任务"
      onClose={onClose}
      width={520}
      footer={
        <button type="button" className="btn-plain" onClick={onClose}>
          关闭
        </button>
      }
    >
      <div className="share-modal-section">
        <div className="share-modal-label">访问链接（无需登录）</div>
        {link.phase === "loading" && (
          <div className="share-modal-hint">
            <i className="fa-solid fa-spinner fa-spin" /> 正在生成链接…
          </div>
        )}
        {link.phase === "error" && (
          <div className="share-modal-hint share-modal-error">
            {link.message}
          </div>
        )}
        {link.phase === "ready" && (
          <div className="share-modal-link-row">
            <input
              type="text"
              className="share-modal-link-input"
              value={link.url}
              readOnly
              onFocus={(e) => e.target.select()}
              aria-label="分享链接"
            />
            <button
              type="button"
              className="btn-primary share-modal-copy-btn"
              onClick={() => void copyLink()}
            >
              复制链接
            </button>
          </div>
        )}
        <p className="share-modal-hint">
          链接在浏览器中打开只读分享页，含完整对话与会话内产出的文件；删除任务后链接自动失效。
        </p>
      </div>
      <div className="share-modal-section">
        <div className="share-modal-label">导出文件</div>
        <button
          type="button"
          className="btn-plain share-modal-export-btn"
          disabled={exporting}
          onClick={() => void exportFile()}
        >
          <i className="fa-regular fa-file-lines" />
          {exporting ? "导出中…" : "导出 Markdown (.md)"}
        </button>
      </div>
    </Modal>
  );
}
