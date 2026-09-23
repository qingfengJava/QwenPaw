/**
 * UserMessageNav — right-side vertical navigator over user messages
 * (console UserMessageAnchors / navigator variant parity):
 *   - chevron up / down jump to the previous / next user message,
 *   - the middle list button carries a badge with the total user-message
 *     count ("99+" above the cap) and opens a hover directory popover
 *     ("导航 (N)" + locate button + preview / date / attachment stats),
 *   - the active anchor is the user bubble closest to the container top
 *     (first / last at scroll boundaries),
 *   - jump targets scroll to the container top and flash for 1.2s.
 * Renders only once at least 3 user messages exist, like the console.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TimelineItem, UserAttachment } from "../../chat/protocol";

interface UserAnchor {
  /** Timeline key — doubles as the DOM id of the user row. */
  id: string;
  preview: string;
  at?: number;
  attachments?: UserAttachment[];
}

const MIN_ANCHOR_COUNT = 3;
const BADGE_MAX_COUNT = 99;
const BOUNDARY_OFFSET = 4;
const FLASH_DURATION = 1200;
const FLASH_CLASS = "anchor-flash";
/** smooth scrolling is still settling around this point — correct once. */
const SETTLE_DELAY = 420;

export const anchorDomId = (key: string) => `anchor-${key}`;

function badgeText(count: number): string {
  return count > BADGE_MAX_COUNT ? `${BADGE_MAX_COUNT}+` : String(count);
}

function normalizePreview(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function anchorPreview(item: Extract<TimelineItem, { kind: "user" }>): string {
  const text = normalizePreview(item.text || "");
  if (text) {
    return text.length > 60 ? `${text.slice(0, 60)}…` : text;
  }
  const names = (item.attachments ?? []).map((a) => a.name).join(" ");
  return normalizePreview(names) || "用户消息";
}

/** Console getAnchorTimeText parity — `M月D日 HH:mm`. */
function anchorTimeText(at?: number): string {
  if (!at) return "";
  const date = new Date(at < 1e12 ? at * 1000 : at);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Console getAnchorAttachmentText parity — `Image：2 · File：1`. */
function attachmentText(attachments?: UserAttachment[]): string {
  if (!attachments?.length) return "";
  const counts = attachments.reduce<Record<string, number>>((acc, a) => {
    const type = a.type.startsWith("image/") ? "Image" : "File";
    acc[type] = (acc[type] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([type, count]) => `${type}：${count}`)
    .join(" · ");
}

interface UserMessageNavProps {
  /** Ref of the .chat-scroll container (shared with TimelineList). */
  scrollRef: React.RefObject<HTMLDivElement | null>;
  items: TimelineItem[];
}

export default function UserMessageNav({ scrollRef, items }: UserMessageNavProps) {
  const anchors = useMemo<UserAnchor[]>(
    () =>
      items
        .filter((it): it is Extract<TimelineItem, { kind: "user" }> => it.kind === "user")
        .map((it) => ({
          id: it.key,
          preview: anchorPreview(it),
          at: it.at,
          attachments: it.attachments,
        })),
    [items],
  );

  const [activeId, setActiveId] = useState<string | undefined>();
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [directoryOpenVersion, setDirectoryOpenVersion] = useState(0);
  const frameRef = useRef<number | undefined>(undefined);
  const listRef = useRef<HTMLDivElement | null>(null);
  const activeItemRef = useRef<HTMLButtonElement | null>(null);

  /** Console getActiveAnchorId parity — boundary first, else nearest to top. */
  const updateActive = useCallback(() => {
    const el = scrollRef.current;
    if (!el || anchors.length === 0) return;
    const maxScrollDistance = Math.max(el.scrollHeight - el.clientHeight, 0);
    if (maxScrollDistance <= BOUNDARY_OFFSET || el.scrollTop <= BOUNDARY_OFFSET) {
      setActiveId(anchors[0].id);
      return;
    }
    if (maxScrollDistance - el.scrollTop <= BOUNDARY_OFFSET) {
      setActiveId(anchors[anchors.length - 1].id);
      return;
    }
    const topLine = el.getBoundingClientRect().top;
    let best: string | undefined;
    let minDistance = Number.POSITIVE_INFINITY;
    anchors.forEach((anchor) => {
      const node = document.getElementById(anchorDomId(anchor.id));
      if (!node) return;
      const distance = Math.abs(node.getBoundingClientRect().top - topLine);
      if (distance < minDistance) {
        minDistance = distance;
        best = anchor.id;
      }
    });
    if (best) setActiveId(best);
  }, [anchors, scrollRef]);

  useEffect(() => {
    if (anchors.length < MIN_ANCHOR_COUNT) return;
    const el = scrollRef.current;
    if (!el) return;
    updateActive();
    const onScroll = () => {
      if (frameRef.current !== undefined) return;
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = undefined;
        updateActive();
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      el.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frameRef.current !== undefined) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, [anchors.length, scrollRef, updateActive]);

  /**
   * Scroll the target bubble to the container top (smooth + one settle
   * correction) and flash it for 1.2s — the console jump behaviour.
   */
  const jumpTo = useCallback(
    (id: string) => {
      const el = scrollRef.current;
      if (!el) return;
      setActiveId(id);
      const target = document.getElementById(anchorDomId(id));
      if (!target) return;
      el.scrollBy({
        top: target.getBoundingClientRect().top - el.getBoundingClientRect().top,
        behavior: "smooth",
      });
      window.setTimeout(() => {
        const el2 = scrollRef.current;
        const target2 = document.getElementById(anchorDomId(id));
        if (!el2 || !target2) return;
        el2.scrollBy({ top: target2.getBoundingClientRect().top - el2.getBoundingClientRect().top });
      }, SETTLE_DELAY);
      window.setTimeout(() => {
        const node = document.getElementById(anchorDomId(id));
        if (!node) return;
        node.classList.remove(FLASH_CLASS);
        // Restart the animation if a previous flash is still attached.
        void node.offsetWidth;
        node.classList.add(FLASH_CLASS);
        window.setTimeout(() => node.classList.remove(FLASH_CLASS), FLASH_DURATION);
      }, SETTLE_DELAY + 10);
    },
    [scrollRef],
  );

  // Keep the active entry centered inside the directory whenever it opens
  // (console scrollActiveItemIntoView parity).
  useEffect(() => {
    if (!directoryOpen) return;
    const frame = window.requestAnimationFrame(() => {
      const item = activeItemRef.current;
      const list = listRef.current;
      if (!item || !list) return;
      list.scrollTo({
        top: Math.max(0, item.offsetTop - (list.clientHeight - item.offsetHeight) / 2),
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [directoryOpen, directoryOpenVersion]);

  if (anchors.length < MIN_ANCHOR_COUNT) return null;

  const activeIndex = activeId ? anchors.findIndex((a) => a.id === activeId) : anchors.length - 1;
  const normalizedIndex = activeIndex >= 0 ? activeIndex : anchors.length - 1;
  const previousAnchor = normalizedIndex > 0 ? anchors[normalizedIndex - 1] : undefined;
  const nextAnchor =
    normalizedIndex < anchors.length - 1 ? anchors[normalizedIndex + 1] : undefined;

  return (
    <nav className="chat-anchor-nav" aria-label="用户消息导航">
      <button
        type="button"
        className="chat-anchor-nav-button"
        aria-label="跳转到上一条用户消息"
        disabled={!previousAnchor}
        onClick={() => previousAnchor && jumpTo(previousAnchor.id)}
      >
        <i className="fa-solid fa-chevron-up" />
      </button>

      <div
        className="chat-anchor-menu-wrap"
        onMouseEnter={() => {
          setDirectoryOpen(true);
          setDirectoryOpenVersion((v) => v + 1);
        }}
        onMouseLeave={() => setDirectoryOpen(false)}
      >
        <button
          type="button"
          className={`chat-anchor-nav-button chat-anchor-nav-button-menu${
            activeId ? " chat-anchor-nav-button-active" : ""
          }`}
          aria-label="打开用户消息导航目录"
        >
          <i className="fa-solid fa-list-ul" />
          <span className="chat-anchor-nav-count">{badgeText(anchors.length)}</span>
        </button>
        {directoryOpen && (
          <div className="chat-anchor-directory">
            <div className="chat-anchor-directory-title">
              <span>导航 ({anchors.length})</span>
              <button
                type="button"
                className="chat-anchor-directory-locate"
                aria-label="定位到当前用户消息"
                disabled={!activeId}
                onClick={() => {
                  const item = activeItemRef.current;
                  const list = listRef.current;
                  if (!item || !list) return;
                  list.scrollTo({
                    top: Math.max(0, item.offsetTop - (list.clientHeight - item.offsetHeight) / 2),
                    behavior: "smooth",
                  });
                }}
              >
                <i className="fa-solid fa-crosshairs" />
              </button>
            </div>
            <div className="chat-anchor-directory-list" ref={listRef}>
              {anchors.map((anchor) => {
                const timeText = anchorTimeText(anchor.at);
                const attText = attachmentText(anchor.attachments);
                const active = anchor.id === activeId;
                return (
                  <button
                    type="button"
                    key={anchor.id}
                    className={`chat-anchor-directory-item${active ? " active" : ""}`}
                    ref={active ? activeItemRef : undefined}
                    onClick={() => {
                      jumpTo(anchor.id);
                      setDirectoryOpen(false);
                    }}
                  >
                    <span className="chat-anchor-directory-main">
                      <span className="chat-anchor-directory-msg">{anchor.preview}</span>
                      {timeText && <span className="chat-anchor-directory-time">{timeText}</span>}
                    </span>
                    {attText && <span className="chat-anchor-directory-atts">{attText}</span>}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        className="chat-anchor-nav-button"
        aria-label="跳转到下一条用户消息"
        disabled={!nextAnchor}
        onClick={() => nextAnchor && jumpTo(nextAnchor.id)}
      >
        <i className="fa-solid fa-chevron-down" />
      </button>
    </nav>
  );
}
