/**
 * hooks/useManageable.ts — 后台配置域「可管理」判定的唯一前端读面。
 *
 * 数据单一来源：manageable 由后端注册表按 viewer 一次快照批量判定
 * （manage grants + 角色 + owner 兜底），前端**禁止本地复刻判定逻辑**，
 * 只从 `GET /agents/registry` 读取结果。工作台 Tab 过滤、ModelSelector
 * 只读化都消费本 hook，避免各页面重复请求与口径漂移。
 *
 * 缓存策略：模块级 promise 去重——同一浏览器标签页内多个消费者共享一次
 * 注册表拉取；治理写入后可调 invalidateManageable() 主动失效重取。
 *
 * fail-closed 语义：加载失败或员工不在可见注册表中时返回 false（与后端
 * 写闸门同源），前端据此隐藏管理面而非误放行。
 */
import { useEffect, useState } from "react";
import { employeeRegistryApi } from "@/api/modules/employeeRegistry";

/** agent_id → 当前 viewer 是否可配置该员工。 */
type ManageableMap = Record<string, boolean>;

let cachePromise: Promise<ManageableMap> | null = null;
let cacheValue: ManageableMap | null = null;

/** 拉取（或复用缓存的）可管理映射；并发调用共享同一 promise。 */
function loadManageableMap(): Promise<ManageableMap> {
  if (cachePromise) {
    return cachePromise;
  }
  cachePromise = employeeRegistryApi
    .list()
    .then((rows) => {
      const map: ManageableMap = {};
      rows.forEach((row) => {
        map[row.agent_id] = row.manageable;
      });
      cacheValue = map;
      return map;
    })
    .catch((error) => {
      // 失败清空 in-flight promise 以便下次重试；错误语义交调用方 fail-closed
      cachePromise = null;
      throw error;
    });
  return cachePromise;
}

/** 主动失效缓存（治理写入 / 授权变更后调用，下次 hook 挂载重新拉取）。 */
export function invalidateManageable(): void {
  cachePromise = null;
  cacheValue = null;
}

export interface ManageableState {
  /**
   * 当前 viewer 是否可配置该员工。
   * null = 尚未确定（加载中或拉取失败）；调用方按 fail-closed（视作 false）处理。
   */
  manageable: boolean | null;
  /** 是否仍在首次加载（用于区分「加载中」与「已确定不可管理」）。 */
  loading: boolean;
}

/**
 * 读取某员工的可管理判定（共享模块级缓存，多消费者仅拉取一次注册表）。
 *
 * @param agentId 目标员工 agent_id；为空时返回 manageable=null（无从判定）。
 */
export function useManageable(
  agentId: string | undefined | null,
): ManageableState {
  const [map, setMap] = useState<ManageableMap | null>(cacheValue);
  const [loading, setLoading] = useState<boolean>(cacheValue === null);

  useEffect(() => {
    // 已有缓存：直接落地，不再发请求
    if (cacheValue) {
      setMap(cacheValue);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    loadManageableMap()
      .then((next) => {
        if (!alive) return;
        setMap(next);
        setLoading(false);
      })
      .catch(() => {
        if (!alive) return;
        // 拉取失败：map 保持 null，消费者按 fail-closed 处理
        setMap(null);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (!agentId) {
    return { manageable: null, loading: false };
  }
  // map 未就绪（加载中/失败）→ null；就绪但员工不在可见注册表 → false
  const manageable = map ? (map[agentId] ?? false) : null;
  return { manageable, loading };
}
