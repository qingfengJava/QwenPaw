/**
 * useBriefStats.ts — 员工轻量统计 hook（档案栏迷你统计 + 概览卡共用）。
 *
 * 模块级 60s TTL 缓存：档案栏与概览页同屏挂载时只发一次请求，
 * 切回员工 60s 内复用缓存，避免轮询风暴。统计失败静默降级为
 * null（调用方渲染骨架/占位），不阻塞档案呈现。
 */
import { useEffect, useState } from "react";
import {
  agentStatsApi,
  type AgentBriefStats,
} from "@/api/modules/agentStats";

interface CacheEntry {
  at: number;
  data: AgentBriefStats;
}

const TTL_MS = 60_000;
const cache = new Map<string, CacheEntry>();

export function useBriefStats(aid: string) {
  const [stats, setStats] = useState<AgentBriefStats | null>(
    () => cache.get(aid)?.data ?? null,
  );
  const [loading, setLoading] = useState(!cache.has(aid));

  useEffect(() => {
    let alive = true;
    const hit = cache.get(aid);
    if (hit && Date.now() - hit.at < TTL_MS) {
      setStats(hit.data);
      setLoading(false);
      return;
    }
    setLoading(true);
    agentStatsApi
      .getAgentBriefStats(aid)
      .then((data) => {
        cache.set(aid, { at: Date.now(), data });
        if (alive) setStats(data);
      })
      .catch(() => {
        // 统计不可用时保持 null，由调用方渲染占位。
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [aid]);

  return { stats, loading };
}
