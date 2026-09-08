/**
 * useExpertAvatarUri — DiceBear 形象 → dataUri 字符串（img src 直用）。
 *
 * ExpertAvatar 组件的 hook 化变体：给需要「纯字符串头像源」的场景
 * （如 Chat 欢迎屏的 SDK welcome.avatar 配置项）复用同一套解析规则
 * （utils/expertAvatar.ts）：显式 dicebear:// 配置 → 按配置；否则按
 * expertId 稳定自动分配。未就绪/失败返回 null，调用方自行回退。
 */
import { useEffect, useMemo, useState } from "react";
import { renderExpertAvatar, resolveExpertAvatar } from "../utils/expertAvatar";

export function useExpertAvatarUri(
  icon: string | null | undefined,
  expertId: string,
): string | null {
  const resolved = useMemo(
    () => resolveExpertAvatar(icon, expertId),
    [icon, expertId],
  );
  const [dataUri, setDataUri] = useState<string | null>(null);

  useEffect(() => {
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
  }, [resolved.style, resolved.seed]);

  return dataUri;
}
