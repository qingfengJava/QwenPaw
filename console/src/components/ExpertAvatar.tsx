/**
 * ExpertAvatar.tsx — 数字员工形象头像（DiceBear 确定性 SVG）。
 *
 * 解析规则见 utils/expertAvatar.ts：显式 dicebear:// 配置 → 按配置；
 * icon 为空 → 按 expertId 自动分配；旧 emoji 值 → 回退首字符渐变。
 * SVG 经 toDataUri() 走 img src，不用 dangerouslySetInnerHTML。
 */
import { useEffect, useState, type CSSProperties } from "react";
import { avatarGradient } from "@/utils/avatarGradient";
import {
  renderExpertAvatar,
  resolveExpertAvatar,
} from "@/utils/expertAvatar";

export interface ExpertAvatarProps {
  /** experts.icon 原始值（可空）。 */
  icon?: string | null;
  /** 专家 ID（自动分配的稳定性种子）。 */
  expertId: string;
  /** 展示名（回退态取首字符）。 */
  name?: string;
  /** 直径（px）。 */
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export default function ExpertAvatar({
  icon,
  expertId,
  name = "",
  size = 32,
  className,
  style,
}: ExpertAvatarProps) {
  const resolved = resolveExpertAvatar(icon, expertId);
  const [dataUri, setDataUri] = useState<string | null>(null);

  useEffect(() => {
    if (!resolved) {
      setDataUri(null);
      return;
    }
    let alive = true;
    renderExpertAvatar(resolved)
      .then((uri) => {
        if (alive) setDataUri(uri);
      })
      .catch(() => {
        if (alive) setDataUri(null);
      });
    return () => {
      alive = false;
    };
  }, [resolved?.style, resolved?.seed]);

  if (!dataUri) {
    return (
      <div
        className={className}
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          background: avatarGradient(expertId + name),
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.round(size * 0.38),
          fontWeight: 600,
          flexShrink: 0,
          ...style,
        }}
      >
        {(name || expertId || "?").slice(0, 1).toUpperCase()}
      </div>
    );
  }

  return (
    <img
      className={className}
      src={dataUri}
      width={size}
      height={size}
      alt={name || expertId}
      loading="lazy"
      style={{
        borderRadius: "50%",
        flexShrink: 0,
        objectFit: "cover",
        display: "block",
        ...style,
      }}
    />
  );
}
