/**
 * ChatComposer — the full backend-parity chat input: attachment picker with
 * preview chips (POST /console/upload), browser speech input, slash-command
 * suggestions, execution-mode / approval / agent selectors, context ring,
 * 10000-char counter with live display, stop-aware send button and the
 * backend disclaimer line. Visual layout mirrors the console Sender.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { chatApi, loopApi, type LoopModeInfo } from "../../api/modules";
import { useToast } from "../Toast";
import AgentSelector from "./AgentSelector";
import ApprovalSelector from "./ApprovalSelector";
import ContextRing from "./ContextRing";
import LoopModeSelector from "./LoopModeSelector";
import {
  resolveLoopModeDescription,
  useChatPrefs,
} from "../../stores/chatPrefs";

export const MAX_INPUT_LENGTH = 10000;

export interface PendingAttachment {
  uid: string;
  name: string;
  type: string;
  size: number;
  /** Stored name returned by /console/upload (what the wire protocol uses). */
  storedUrl: string;
  /** Browsable preview URL for image thumbnails. */
  previewUrl: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechCtor = new () => SpeechRecognitionLike;

function getSpeechCtor(): SpeechCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: SpeechCtor;
    webkitSpeechRecognition?: SpeechCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export default function ChatComposer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  disabled,
  contextRatio,
  attachments,
  onAttachmentsChange,
  placeholder,
  disclaimer = "懂你所需，伴你左右",
}: {
  value: string;
  onChange: (value: string) => void;
  /** Receives the raw text plus the pending attachments. */
  onSend: (text: string, attachments: PendingAttachment[]) => void;
  onStop?: () => void;
  busy?: boolean;
  disabled?: boolean;
  /** 0..1 from the last turn_usage context ratio. */
  contextRatio?: number;
  attachments: PendingAttachment[];
  onAttachmentsChange: (next: PendingAttachment[]) => void;
  /** Home uses its own launcher placeholder; Chat keeps the backend one. */
  placeholder?: string;
  disclaimer?: string;
}) {
  const toast = useToast();
  const loopModes = useChatPrefs((s) => s.loopModes);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(0);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  /** Command that was just applied/filled — hide the palette for it until the
   * first token changes (Tab/Enter/click fill would otherwise re-match). */
  const slashDismissedRef = useRef<string | null>(null);

  // Preload the loop catalog on mount so cold-start slash input shows the
  // full /goal /mission list without opening the mode selector first.
  useEffect(() => {
    if (loopModes.length > 1) return;
    loopApi
      .list()
      .then((modes) => {
        if (Array.isArray(modes) && modes.length > 0) {
          useChatPrefs.getState().setLoopModes(modes);
        }
      })
      .catch(() => {
        // default-only catalog remains functional
      });
  }, [loopModes.length]);

  const hasText = value.trim().length > 0;

  // ---- slash command suggestions (loop modes + approval commands) ----
  const slashSuggestions = useMemo(() => {
    const first = value.trimStart().split(/\s/, 1)[0] ?? "";
    if (!first.startsWith("/")) return [];
    const typed = first.slice(1).toLowerCase();
    const fromModes = loopModes
      .filter((m) => m.slash_command && m.slash_command.startsWith(typed))
      .map((m: LoopModeInfo) => ({
        command: `/${m.slash_command}`,
        description: resolveLoopModeDescription(m),
      }));
    const fixed = [
      { command: "/approve", description: "审批通过当前待确认的工具调用" },
      { command: "/deny", description: "拒绝当前待确认的工具调用" },
    ].filter((s) => s.command.slice(1).startsWith(typed));
    return [...fromModes, ...fixed];
  }, [value, loopModes]);

  const slashOpen =
    !busy &&
    slashSuggestions.length > 0 &&
    value.trimStart().startsWith("/") &&
    (value.trimStart().split(/\s/, 1)[0] ?? "") !== slashDismissedRef.current;

  useEffect(() => {
    setSlashIndex(0);
  }, [slashSuggestions.length]);

  const applySuggestion = (command: string) => {
    const rest = value.trimStart().split(/\s/).slice(1).join(" ");
    slashDismissedRef.current = command;
    onChange(`${command}${rest ? ` ${rest}` : " "}`);
    textRef.current?.focus();
  };

  // ---- auto-grow ----
  const handleInput = (next: string) => {
    if (next.length > MAX_INPUT_LENGTH) {
      next = next.slice(0, MAX_INPUT_LENGTH);
    }
    const nextToken = next.trimStart().split(/\s/, 1)[0] ?? "";
    if (nextToken !== slashDismissedRef.current) {
      slashDismissedRef.current = null;
    }
    onChange(next);
    const el = textRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  };

  // ---- attachments ----
  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) {
      setUploading((n) => n + 1);
      try {
        const res = await chatApi.upload(file);
        const preview = res.url.startsWith("http")
          ? res.url
          : `/api/files/preview/${res.url.replace(/^\/+/, "")}`;
        onAttachmentsChange([
          ...attachments,
          {
            uid: `${file.name}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            name: file.name,
            type: file.type || "application/octet-stream",
            size: file.size,
            storedUrl: res.url,
            previewUrl: preview,
          },
        ]);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "附件上传失败");
      } finally {
        setUploading((n) => n - 1);
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  // ---- speech ----
  const toggleSpeech = () => {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Ctor = getSpeechCtor();
    if (!Ctor) {
      toast.error("当前浏览器不支持语音输入");
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (e) => {
      const transcript = Array.from({ length: e.results.length })
        .map((_, i) => e.results[i][0]?.transcript ?? "")
        .join("");
      if (transcript) {
        handleInput(value ? `${value} ${transcript}` : transcript);
      }
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  };

  // ---- send ----
  const doSend = useCallback(() => {
    if (busy) {
      onStop?.();
      return;
    }
    if (disabled || (!hasText && attachments.length === 0 && uploading === 0)) {
      return;
    }
    if (uploading > 0) {
      toast.info("附件上传中，请稍候");
      return;
    }
    onSend(value.trim(), attachments);
  }, [
    busy,
    disabled,
    hasText,
    attachments,
    uploading,
    onStop,
    onSend,
    value,
    toast,
  ]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (slashOpen && e.key === "Escape") {
      // Drop the half-typed command token — closes the palette (hint promise).
      e.preventDefault();
      const rest = value.trimStart().split(/\s/).slice(1).join(" ");
      handleInput(rest);
      return;
    }
    if (slashOpen && ["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      setSlashIndex((i) => {
        const n = slashSuggestions.length;
        return e.key === "ArrowDown" ? (i + 1) % n : (i - 1 + n) % n;
      });
      return;
    }
    if (slashOpen && ["Tab", "Enter"].includes(e.key) && slashSuggestions[slashIndex]) {
      if (e.key === "Enter" && e.shiftKey) return;
      e.preventDefault();
      applySuggestion(slashSuggestions[slashIndex].command);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
    if (e.key === "Escape") {
      recognitionRef.current?.stop();
    }
  };

  return (
    <div className="chat-composer" data-busy={busy ? "true" : undefined}>
      {slashOpen && (
        <div className="slash-suggestions">
          {slashSuggestions.map((s, i) => (
            <button
              type="button"
              key={s.command}
              className={`slash-item${i === slashIndex ? " active" : ""}`}
              onMouseEnter={() => setSlashIndex(i)}
              onClick={() => applySuggestion(s.command)}
            >
              <span className="slash-command">{s.command}</span>
              <span className="slash-desc">{s.description}</span>
            </button>
          ))}
          <div className="slash-hint">↑↓ 选择 · Tab/Enter 填充 · Esc 关闭</div>
        </div>
      )}

      {(attachments.length > 0 || uploading > 0) && (
        <div className="composer-attachments">
          {attachments.map((a) => (
            <div key={a.uid} className="attachment-chip">
              {a.type.startsWith("image/") ? (
                <img src={a.previewUrl} alt={a.name} />
              ) : (
                <i className="fa-solid fa-file-lines" />
              )}
              <span className="attachment-name" title={a.name}>
                {a.name}
              </span>
              <button
                type="button"
                className="attachment-remove"
                aria-label={`移除 ${a.name}`}
                onClick={() =>
                  onAttachmentsChange(attachments.filter((x) => x.uid !== a.uid))
                }
              >
                <i className="fa-solid fa-xmark" />
              </button>
            </div>
          ))}
          {uploading > 0 && (
            <div className="attachment-chip uploading">
              <i className="fa-solid fa-spinner fa-spin" />
              <span>上传中…（{uploading}）</span>
            </div>
          )}
        </div>
      )}

      <textarea
        ref={textRef}
        className="composer-textarea"
        placeholder={
          placeholder ??
          '↑↓ 浏览消息 · "/" 快捷指令（审批时 "/approve" 或 "/deny"）'
        }
        value={value}
        disabled={disabled}
        rows={1}
        onChange={(e) => handleInput(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      <div className="composer-toolbar">
        <div className="composer-left">
          <button
            type="button"
            className={`composer-icon-btn${listening ? " listening" : ""}`}
            onClick={toggleSpeech}
            title={listening ? "停止语音输入" : "语音输入"}
            aria-label="语音输入"
          >
            <i className="fa-solid fa-microphone" />
          </button>
          <button
            type="button"
            className="composer-icon-btn"
            onClick={() => fileRef.current?.click()}
            title="添加附件"
            aria-label="添加附件"
          >
            <i className="fa-solid fa-paperclip" />
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={(e) => void handleFiles(e.target.files)}
          />
          <LoopModeSelector />
        </div>

        <div className="composer-right">
          <ContextRing ratio={contextRatio ?? 0} />
          <AgentSelector />
          <ApprovalSelector />
          <span
            className={`composer-counter${value.length >= MAX_INPUT_LENGTH ? " max" : ""}`}
          >
            {value.length}/{MAX_INPUT_LENGTH}
          </span>
          <button
            type="button"
            className={`composer-send${busy || hasText || attachments.length > 0 ? " active" : ""}`}
            onClick={doSend}
            disabled={busy && !onStop ? true : disabled}
            aria-label={busy ? "停止生成" : "发送"}
            title={busy ? "停止生成" : "发送"}
          >
            <i className={busy ? "fa-solid fa-stop" : "fa-solid fa-arrow-up"} />
          </button>
        </div>
      </div>

      <div className="composer-disclaimer">{disclaimer}</div>
    </div>
  );
}
