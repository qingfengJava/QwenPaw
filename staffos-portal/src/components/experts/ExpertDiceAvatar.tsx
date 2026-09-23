/**
 * ExpertDiceAvatar — 数字员工 DiceBear 形象头像（xianwork 前台版）。
 *
 * 仅在 icon 为显式 "dicebear://<style>/<seed>" 配置时渲染 img（填充
 * 父容器）；其余值返回 null，由 ExpertCard 保持 Font Awesome 原渲染。
 * 渲染规则与 console/src/components/ExpertAvatar.tsx 同源。
 */
import { useEffect, useState } from "react";
import {
  renderExpertAvatar,
  resolveExpertAvatar,
} from "../../utils/expertAvatar";

export interface ExpertDiceAvatarProps {
  icon?: string | null;
  expertId: string;
  name?: string;
}

export default function ExpertDiceAvatar({
  icon,
  expertId,
  name = "",
}: ExpertDiceAvatarProps) {
  const resolved = icon?.trim().startsWith("dicebear://")
    ? resolveExpertAvatar(icon, expertId)
    : null;
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
    return null;
  }

  return (
    <img
      src={dataUri}
      width={52}
      height={52}
      alt={name || expertId}
      loading="lazy"
      style={{
        width: "100%",
        height: "100%",
        borderRadius: "50%",
        objectFit: "cover",
        display: "block",
      }}
    />
  );
}
