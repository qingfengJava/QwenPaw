/**
 * teamRuns store — the single source of truth for workforce team runs
 * (list + detail cache), following the chats-store pattern: every
 * mutation ends with one reload/detailRefresh so all surfaces stay
 * consistent without per-component refetching.
 */
import { create } from "zustand";
import { workforceApi } from "../api/modules";
import type { TeamRun } from "../api/modules";

/** Monotonic sequence: a stale in-flight reload is discarded. */
let reloadSeq = 0;
let detailSeq = 0;

interface TeamRunsState {
  /** Personal-scope runs (initiator = caller), newest first. */
  runs: TeamRun[];
  loading: boolean;
  error: string | null;
  reload: (params?: { project_id?: string; team_id?: string }) => Promise<void>;
  /** Detail cache: only the run being viewed (RunDetail owns refresh-on-SSE). */
  detail: TeamRun | null;
  detailLoading: boolean;
  loadDetail: (runId: string) => Promise<void>;
  /** Drop the cached detail when leaving the page. */
  clearDetail: () => void;
}

export const useTeamRunsStore = create<TeamRunsState>()((set) => ({
  runs: [],
  loading: false,
  error: null,

  reload: async (params) => {
    const seq = ++reloadSeq;
    set({ loading: true, error: null });
    try {
      const result = await workforceApi.list(params ?? {});
      if (seq !== reloadSeq) return; // superseded by a newer reload
      set({ runs: result, loading: false });
    } catch (err) {
      if (seq !== reloadSeq) return;
      set({ loading: false, error: String(err) });
    }
  },

  detail: null,
  detailLoading: false,

  loadDetail: async (runId: string) => {
    const seq = ++detailSeq;
    set({ detailLoading: true });
    try {
      const detail = await workforceApi.detail(runId);
      if (seq !== detailSeq) return;
      set({ detail, detailLoading: false });
    } catch (err) {
      if (seq !== detailSeq) return;
      set({ detailLoading: false });
      throw err;
    }
  },

  clearDetail: () => {
    detailSeq += 1; // invalidate any in-flight load
    set({ detail: null, detailLoading: false });
  },
}));
