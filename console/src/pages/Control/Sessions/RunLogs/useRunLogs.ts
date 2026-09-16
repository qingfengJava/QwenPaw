/**
 * Run-logs data hook: server-side filtered, paged query against the
 * day-sharded index. Mirrors ``useSessions`` but keeps all filtering on
 * the backend (the index can outgrow a frontend filter).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDeferredValue } from "react";
import dayjs from "dayjs";
import {
  runLogsApi,
  type RunLogItem,
} from "../../../../api/modules/runLogs";
import {
  userProfilesApi,
  type UserProfile,
} from "../../../../api/modules/userProfiles";

export type RunStatusFilter = "" | "running" | "success" | "failed";
export type RunEnvironmentFilter = "" | "online" | "debug";

export interface RunLogQuery {
  status: RunStatusFilter;
  environment: RunEnvironmentFilter;
  channel: string;
  /** Sender identity filter; "" = all users. */
  user: string;
  keyword: string;
  /** Epoch seconds window; null = no bound. */
  start: number | null;
  end: number | null;
  page: number;
  pageSize: number;
}

const BASE_QUERY: RunLogQuery = {
  status: "",
  environment: "",
  channel: "",
  user: "",
  keyword: "",
  start: null,
  end: null,
  page: 1,
  pageSize: 20,
};

/** Default window: the last 7 days including today (competitor default). */
function defaultQuery(): RunLogQuery {
  const now = dayjs();
  return {
    ...BASE_QUERY,
    start: now.subtract(6, "day").startOf("day").unix(),
    end: now.endOf("day").unix(),
  };
}

export function useRunLogs(agentId: string | undefined) {
  const [query, setQuery] = useState<RunLogQuery>(defaultQuery);
  const [items, setItems] = useState<RunLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 用户筛选下拉选项（distinct 发起人，随数据域加载一次）。
  const [runUsers, setRunUsers] = useState<string[]>([]);
  // username -> 展示资料（display_name/avatar），批量解析避免逐行回源。
  const [profiles, setProfiles] = useState<Map<string, UserProfile>>(
    () => new Map(),
  );
  // Keyword typing stays snappy; the deferred value drives the request.
  const deferredKeyword = useDeferredValue(query.keyword);
  const requestIdRef = useRef(0);

  const effectiveQuery = useMemo(
    () => ({ ...query, keyword: deferredKeyword }),
    [query, deferredKeyword],
  );

  // 用户下拉选项与列表同域（agentId 变化时重拉）。
  useEffect(() => {
    if (!agentId) {
      setRunUsers([]);
      return;
    }
    let cancelled = false;
    runLogsApi
      .listRunUsers(agentId)
      .then((res) => {
        if (!cancelled) setRunUsers(res.users || []);
      })
      .catch(() => {
        // 选项加载失败不阻塞列表（可手输场景不存在，仅少筛选项）。
        if (!cancelled) setRunUsers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  // 当前页出现的发起人批量解析为展示资料（一次请求，非逐行）。
  useEffect(() => {
    const ids = [
      ...new Set(items.map((item) => item.user_id || "").filter(Boolean)),
    ];
    if (ids.length === 0) {
      return;
    }
    let cancelled = false;
    userProfilesApi
      .getProfiles(ids)
      .then((map) => {
        if (!cancelled && map.size > 0) {
          setProfiles((prev) => new Map([...prev, ...map]));
        }
      })
      .catch(() => {
        // 资料解析失败时回退 username 展示，不阻塞列表。
      });
    return () => {
      cancelled = true;
    };
  }, [items]);

  const fetchLogs = useCallback(async () => {
    if (!agentId) {
      setItems([]);
      setTotal(0);
      return;
    }
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const offset = (effectiveQuery.page - 1) * effectiveQuery.pageSize;
      const response = await runLogsApi.listRunLogs(
        {
          status: effectiveQuery.status || undefined,
          environment: effectiveQuery.environment || undefined,
          channel: effectiveQuery.channel || undefined,
          user: effectiveQuery.user || undefined,
          q: effectiveQuery.keyword || undefined,
          start: effectiveQuery.start ?? undefined,
          end: effectiveQuery.end ?? undefined,
          limit: effectiveQuery.pageSize,
          offset,
        },
        agentId,
      );
      // Drop stale responses when filters change quickly.
      if (requestId !== requestIdRef.current) {
        return;
      }
      setItems(response.items || []);
      setTotal(response.total || 0);
    } catch (err) {
      if (requestId === requestIdRef.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [agentId, effectiveQuery]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const patchQuery = useCallback((patch: Partial<RunLogQuery>) => {
    setQuery((prev) => ({ ...prev, page: 1, ...patch }));
  }, []);

  const setPage = useCallback((page: number, pageSize: number) => {
    setQuery((prev) => ({ ...prev, page, pageSize }));
  }, []);

  const reset = useCallback(() => setQuery(defaultQuery()), []);

  return {
    items,
    total,
    loading,
    error,
    query,
    patchQuery,
    setPage,
    reset,
    refresh: fetchLogs,
    runUsers,
    profiles,
  };
}
