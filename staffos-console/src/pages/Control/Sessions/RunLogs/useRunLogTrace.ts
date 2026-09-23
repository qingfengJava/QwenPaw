/**
 * useRunLogTrace — fetch one run's trace for the detail page.
 * Logic moved verbatim from the former detail drawer, keyed by
 * (agentId, runId) so a page refresh deep-link works on its own.
 */
import { useEffect, useState } from "react";
import { runLogsApi, type RunLogTrace } from "../../../../api/modules/runLogs";

export function useRunLogTrace(
  agentId: string | undefined,
  runId: string | undefined,
) {
  const [trace, setTrace] = useState<RunLogTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId || !runId) {
      setTrace(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    runLogsApi
      .getRunLog(agentId, runId)
      .then((data) => {
        if (!cancelled) {
          setTrace(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, runId]);

  return { trace, loading, error };
}
