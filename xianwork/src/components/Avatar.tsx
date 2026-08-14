/**
 * Avatar — first-character circle avatar (prototype L200-211).
 * `color` defaults to the accent green; deterministic palette otherwise.
 */
const PALETTE = ["#64748b", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444"];

export interface AvatarProps {
  name: string;
  size?: number;
  color?: string;
  className?: string;
}

function pickColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length];
}

export default function Avatar({
  name,
  size = 28,
  color,
  className = "user-avatar",
}: AvatarProps) {
  const label = (name || "?").trim().charAt(0).toUpperCase();
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(10, Math.round(size * 0.46)),
        ...(color ? { backgroundColor: color } : {}),
      }}
    >
      {label}
    </div>
  );
}

export { pickColor };
