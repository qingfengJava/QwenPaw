/**
 * ContextRing — context-window indicator aligned with the console's
 * ContextUsageIndicator: 20px ring without an inner number, the same
 * five-step color scale, and a hover/click popover showing turn tokens,
 * context occupancy plus the full context-management entries (turn tokens
 * stay hidden on the zeroed fresh-session seed, console parity). Both
 * actions match the console chat box: "压缩" submits the /compact command
 * over the same /api/console/chat SSE plane, "新对话" starts a fresh
 * session.
 *
 * Popover interaction mirrors the console antd Popover (trigger hover+click):
 * a 150ms enter delay opens on hover, leaving only schedules a close after a
 * 120ms grace period — cancelled when the pointer reaches the popover, which
 * hangs 8px above the ring — and a click pins the popover open until the
 * ring is clicked again, focus leaves the whole wrap, Escape is pressed or
 * an outside pointer-down lands elsewhere.
 */
import { useEffect, useRef, useState } from "react";
import type { TurnUsage } from "../../chat/protocol";

const RING_SIZE = 20;
const RING_STROKE = 3;
const RING_R = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRC = 2 * Math.PI * RING_R;

/** Console Popover timing — mouseEnterDelay 0.15s / mouseLeaveDelay 0.1s. */
const OPEN_DELAY_MS = 150;
const CLOSE_DELAY_MS = 120;

/** Same five-step scale as the console ContextUsageIndicator. */
function ringColor(pct: number): string {
  if (pct >= 95) return "#cf1322";
  if (pct >= 85) return "#f5222d";
  if (pct >= 75) return "#fa8c16";
  if (pct >= 50) return "#faad14";
  return "#52c41a";
}

/** Compact 1.5K / 1.2M formatting (console utils/formatNumber parity). */
function formatCompact(n?: number): string {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  if (v < 0) return "0";
  const fmt = (x: number) =>
    x % 1 === 0 ? x.toFixed(0) : x.toFixed(1).replace(/\.0$/, "");
  if (v >= 1e9) return fmt(v / 1e9) + "B";
  if (v >= 1e6)
    return v / 1e6 >= 999.95 ? fmt(v / 1e9) + "B" : fmt(v / 1e6) + "M";
  if (v >= 1e3)
    return v / 1e3 >= 999.95 ? fmt(v / 1e6) + "M" : fmt(v / 1e3) + "K";
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export default function ContextRing({
  usage,
  onCompact,
  onNewChat,
}: {
  usage?: TurnUsage | null;
  /** Console parity: submit the /compact command for this session. */
  onCompact?: () => void;
  onNewChat?: () => void;
}) {
  const [open, setOpen] = useState(false);
  /** Click-pinned (console Popover "click" trigger) — hover cannot close it. */
  const [pinned, setPinned] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const openTimer = useRef<number>(0);
  const closeTimer = useRef<number>(0);

  const cancelTimers = () => {
    window.clearTimeout(openTimer.current);
    window.clearTimeout(closeTimer.current);
  };

  // Close timers survive unmount renders otherwise — clear on teardown.
  useEffect(
    () => () => {
      window.clearTimeout(openTimer.current);
      window.clearTimeout(closeTimer.current);
    },
    [],
  );

  // Outside pointer-down closes a click-pinned popover (antd Popover parity).
  useEffect(() => {
    if (!pinned) return;
    const onDocDown = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        cancelTimers();
        setPinned(false);
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", onDocDown);
    return () => window.removeEventListener("pointerdown", onDocDown);
  }, [pinned]);

  // Console parity: nothing to show before the first turn reports usage.
  if (!usage) return null;

  const hoverEnter = () => {
    // Entering the ring or the popover (both wrap descendants) cancels a
    // pending close; opening waits out the enter delay like the console.
    window.clearTimeout(closeTimer.current);
    if (!pinned) {
      window.clearTimeout(openTimer.current);
      openTimer.current = window.setTimeout(() => setOpen(true), OPEN_DELAY_MS);
    }
  };

  const hoverLeave = () => {
    // Grace period: the pointer may cross the ring→popover gap and re-enter
    // (the popover is a wrap descendant) before the close timer fires.
    window.clearTimeout(openTimer.current);
    if (!pinned) {
      closeTimer.current = window.setTimeout(
        () => setOpen(false),
        CLOSE_DELAY_MS,
      );
    }
  };

  const togglePin = () => {
    cancelTimers();
    if (pinned) {
      setPinned(false);
      setOpen(false);
    } else {
      setPinned(true);
      setOpen(true);
    }
  };

  const closeNow = () => {
    cancelTimers();
    setPinned(false);
    setOpen(false);
  };

  const pct = Math.max(
    0,
    Math.min(Number(usage.context_usage_ratio) || 0, 100),
  );
  const color = ringColor(pct);
  const cx = RING_SIZE / 2;
  const pctLabel =
    pct > 0 && pct < 1 ? `${pct.toFixed(1)}%` : `${Math.round(pct)}%`;

  const runAction = (action?: () => void) => {
    closeNow();
    action?.();
  };

  return (
    <span
      ref={wrapRef}
      className="context-ring-wrap"
      onMouseEnter={hoverEnter}
      onMouseLeave={hoverLeave}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.stopPropagation();
          closeNow();
        }
      }}
    >
      <span
        className="context-ring"
        role="button"
        tabIndex={0}
        aria-label="查看本轮 Token 与上下文用量"
        title="查看本轮 Token 与上下文用量"
        onClick={togglePin}
        onFocus={() => {
          if (!pinned) {
            cancelTimers();
            setOpen(true);
          }
        }}
        onBlur={(event) => {
          // Focus moving elsewhere inside the wrap (e.g. onto a popover
          // button) must not dismiss the popover mid-click.
          if (!pinned && !wrapRef.current?.contains(event.relatedTarget)) {
            setOpen(false);
          }
        }}
      >
        <svg width={RING_SIZE} height={RING_SIZE} aria-hidden>
          <circle
            cx={cx}
            cy={cx}
            r={RING_R}
            fill="none"
            stroke="currentColor"
            strokeOpacity={0.2}
            strokeWidth={RING_STROKE}
          />
          <circle
            cx={cx}
            cy={cx}
            r={RING_R}
            fill="none"
            stroke={color}
            strokeWidth={RING_STROKE}
            strokeDasharray={`${RING_CIRC} ${RING_CIRC}`}
            strokeDashoffset={RING_CIRC * (1 - pct / 100)}
            strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cx})`}
          />
        </svg>
      </span>

      {open && (
        <span className="context-ring-pop" role="tooltip">
          {/* Console PopoverBody parity: the turn-tok block renders only
           * with a real turn — the zeroed "/new" seed (usage: null there,
           * total 0 here) shows the context window and entries alone. */}
          {(usage.total_tokens ?? 0) > 0 && (
            <>
              <span className="context-pop-turn">
                本轮 {formatCompact(usage.total_tokens)} tok
              </span>
              <span className="context-pop-sub">
                in {formatCompact(usage.prompt_tokens)} · out{" "}
                {formatCompact(usage.completion_tokens)}
              </span>
            </>
          )}

          <span className="context-pop-head">
            <span className="context-pop-label">上下文窗口：{pctLabel}</span>
            <span className="context-pop-nums">
              {formatCompact(usage.estimated_tokens)}/
              {formatCompact(usage.max_input_length ?? usage.context_size)}
            </span>
          </span>
          <span className="context-pop-bar">
            <span
              className="context-pop-bar-fill"
              style={{ width: `${pct}%`, background: color }}
            />
          </span>

          <span className="context-pop-manage">
            <span className="context-pop-manage-label">上下文管理</span>
            <button
              type="button"
              className="context-pop-btn"
              onClick={() => runAction(onCompact)}
            >
              压缩
            </button>
            <button
              type="button"
              className="context-pop-btn"
              onClick={() => runAction(onNewChat)}
            >
              新对话
            </button>
          </span>
        </span>
      )}
    </span>
  );
}
