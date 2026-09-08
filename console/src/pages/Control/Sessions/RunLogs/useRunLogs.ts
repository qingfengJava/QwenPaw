/**
 * Run-logs data hook: server-side filtered, paged query against the
 * day-sharded index. Mirrors ``useSessions`` but keeps all filtering on
 * the backend (the index can outgrow a frontend filter).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDeferredValue } from "react";
import { runLogsApi, type RunLogItem } from "../../../../api/modules/runLogs";

export type RunStatusFilter = "" | "running" | "success" | "failed";
export type RunEnvironmentFilter = "" | "online" | "debug";

export interface RunLogQuery {
  status: RunStatusFilter;
  environment: RunEnvironmentFilter;
  channel: string;
  keyword: string;
  /** Epoch seconds window; null = no bound. */
  start: number | null;
  end: number | null;
  page: number;
  pageSize: number;
}

const DEFAULT_QUERY: RunLogQuery = {
  status: "",
  environment: "",
  channel: "",
  keyword: "",
  start: null,
  end: null,
  page: 1,
  pageSize: 20,
};

export function useRunLogs(agentId: string | undefined) {
  const [query, setQuery] = useState<RunLogQuery>(DEFAULT_QUERY);
  const [items, setItems] = useState<RunLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Keyword typing stays snappy; the deferred value drives the request.
  const deferredKeyword = useDeferredValue(query.keyword);
  const requestIdRef = useRef(0);

  const effectiveQuery = useMemo(
    () => ({ ...query, keyword: deferredKeyword }),
    [query, deferredKeyword],
  );

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

  const reset = useCallback(() => setQuery(DEFAULT_QUERY), []);

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
  };
}
