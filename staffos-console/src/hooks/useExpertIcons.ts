/**
 * useExpertIcons.ts — experts.icon 值的全局只读缓存。
 *
 * 管理端配置的形象（dicebear:// 值）需要跨页面（数字员工列表行、
 * 档案侧栏等只有 agent id 的场景）读取；这里模块级缓存只拉一次
 * /admin/experts，无权限时静默降级为空表（组件回退自动分配）。
 */
import { useEffect, useState } from "react";
import { adminExpertsApi } from "@/api/modules/admin";

let cache: Record<string, string> | null = null;
let inflight: Promise<Record<string, string>> | null = null;

function loadOnce(): Promise<Record<string, string>> {
  if (cache) {
    return Promise.resolve(cache);
  }
  inflight ??= adminExpertsApi
    .list()
    .then((list) => {
      const map: Record<string, string> = {};
      for (const expert of list) {
        if (expert.icon) {
          map[expert.id] = expert.icon;
        }
      }
      cache = map;
      return map;
    })
    .catch(() => {
      cache = {};
      return cache;
    });
  return inflight;
}

/** 返回 { expertId: icon 原始值 }；未加载完成/无权限时为空对象。 */
export function useExpertIcons(): Record<string, string> {
  const [icons, setIcons] = useState<Record<string, string>>(cache ?? {});

  useEffect(() => {
    let alive = true;
    loadOnce().then((map) => {
      if (alive) setIcons(map);
    });
    return () => {
      alive = false;
    };
  }, []);

  return icons;
}
