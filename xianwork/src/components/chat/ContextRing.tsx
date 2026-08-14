/**
 * ContextRing — circular context-window indicator driven by the turn_usage
 * context ratio the chat stream already reports (same idea as the console's
 * ContextUsageIndicator, minus the compact/new commands).
 */
export default function ContextRing({
  ratio,
  title,
}: {
  ratio: number;
  title?: string;
}) {
  const clamped = Math.min(1, Math.max(0, ratio));
  const pct = Math.round(clamped * 100);
  // 28px ring, 3px stroke — stroke-dasharray drives the fill arc.
  const r = 11;
  const c = 2 * Math.PI * r;
  const color =
    clamped >= 0.9 ? "#e5484d" : clamped >= 0.7 ? "#f59e0b" : "#10a37f";
  return (
    <span
      className="context-ring"
      title={title ?? `上下文已用 ${pct}%`}
      aria-label={`上下文已用 ${pct}%`}
    >
      <svg width="28" height="28" viewBox="0 0 28 28">
        <circle cx="14" cy="14" r={r} fill="none" stroke="#e8e8ec" strokeWidth="3" />
        <circle
          cx="14"
          cy="14"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${c * clamped} ${c}`}
          transform="rotate(-90 14 14)"
        />
        <text x="14" y="17.5" textAnchor="middle" fontSize="8.5" fill="#5c5e66">
          {pct > 0 ? pct : ""}
        </text>
      </svg>
    </span>
  );
}
