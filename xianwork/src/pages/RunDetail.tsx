/**
 * RunDetail — workforce team-run detail: status header (with progress/
 * active-seconds metering), server-authorized decision panel (plan
 * approval / clarify / escalation / resume), the DAG task tree, SSE
 * live refresh, and cancel/pause actions.
 *
 * Data: useTeamRunsStore.loadDetail + subscribeRunEvents (each event
 * triggers one reload — the store is the single invalidation point).
 * 授权与等待语义来自后端投影（allowed_actions/waiting_reason），前端
 * 不自创规则；图从 plan/node 权威投影渲染（RunTaskTree）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PageShell from "../components/PageShell";
import { useToast } from "../components/Toast";
import { useTeamRunsStore } from "../stores/teamRuns";
import { subscribeRunEvents } from "../lib/feedStream";
import {
  ACTIVE_RUN_STATUSES,
  RUN_STATUS_META,
} from "../lib/runStatus";
import { workforceApi } from "../api/modules";
import RunTaskTree from "../components/workforce/RunTaskTree";
import RunDecisionPanel from "../components/workforce/RunDecisionPanel";

export default function RunDetailPage() {
  const toast = useToast();
  const { runId = "" } = useParams();
  const { detail, detailLoading, loadDetail, clearDetail } = useTeamRunsStore();
  const [busy, setBusy] = useState(false);

  // 初载 + 卸载清理（store 详情缓存随路由进出）
  useEffect(() => {
    loadDetail(runId).catch((err) => toast.error(`加载任务失败：${String(err)}`));
    return () => clearDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // SSE 实时刷新：每条事件触发一次详情重载（节流交给 store 的 seq 机制）
  useEffect(() => {
    if (!runId) return;
    const handle = subscribeRunEvents(runId, {
      onEvent: () => {
        loadDetail(runId).catch(() => undefined);
      },
    });
    return () => handle.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const run = detail;

  // ---- 操作（全部走 workforceApi，成功后刷新详情） ----
  const act = useCallback(
    async (fn: () => Promise<unknown>, okText: string) => {
      setBusy(true);
      try {
        await fn();
        toast.success(okText);
        await loadDetail(runId);
      } catch (err) {
        toast.error(`操作失败：${String(err)}`);
      } finally {
        setBusy(false);
      }
    },
    [toast, runId, loadDetail],
  );

  const activeSeconds = useMemo(
    () => (run?.active_seconds ? Math.round(run.active_seconds / 60) : 0),
    [run?.active_seconds],
  );

  if (detailLoading && !run) {
    return (
      <div className="view active">
        <PageShell title="专家团任务" subtitle="加载中…">
          <div className="blank-state">加载中…</div>
        </PageShell>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="view active">
        <PageShell title="专家团任务" subtitle="任务不存在或无权访问">
          <div className="blank-state">任务不存在或无权访问</div>
        </PageShell>
      </div>
    );
  }

  const meta = RUN_STATUS_META[run.status] ?? RUN_STATUS_META.planning;
  const totalTokens = (run.nodes ?? []).reduce((sum, n) => sum + (n.token_cost || 0), 0);
  const progress = run.progress;

  return (
    <div className="view active">
      <PageShell title="专家团任务" subtitle={run.goal}>
        {/* ---- 状态头部卡 ---- */}
        <div className="list-row-card" style={{ marginBottom: 14 }}>
          <div className="list-row-main">
            <div className="card-icon" style={{ width: 42, height: 42, fontSize: 17, marginBottom: 0, color: meta.tone }}>
              <i className={meta.icon} />
            </div>
            <div>
              <div className="list-row-title" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ color: meta.tone }}>{meta.label}</span>
                {progress && (
                  <span className="task-status">
                    节点 {progress.done_nodes}/{progress.total_nodes}
                  </span>
                )}
                <span className="task-status">上下文 v{run.context_version}</span>
                <span className="task-status">返工 {run.repair_count} 次</span>
                {run.replan_count > 0 && (
                  <span className="task-status">重规划 {run.replan_count} 次</span>
                )}
                <span className="task-status">{totalTokens > 0 ? `${(totalTokens / 1000).toFixed(1)}K tokens` : "—"}</span>
                {activeSeconds > 0 && (
                  <span className="task-status">累计执行 {activeSeconds} 分钟</span>
                )}
              </div>
              <div className="list-row-desc">
                发起人 {run.initiator_id === "local" ? "本地用户" : run.initiator_id} ·
                团队 {run.team_id.slice(0, 12)} ·
                {run.created_at?.slice(0, 16)?.replace("T", " ") ?? ""}
                {run.error ? ` · 错误：${run.error.slice(0, 80)}` : ""}
                {run.escalation_reason ? ` · 熔断：${run.escalation_reason.slice(0, 80)}` : ""}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {ACTIVE_RUN_STATUSES.has(run.status) && (
              <>
                <button
                  className="btn-black"
                  disabled={busy}
                  onClick={() => act(() => workforceApi.cancel(run.id), "已请求取消")}
                >
                  取消任务
                </button>
                <button
                  disabled={busy}
                  onClick={() => act(() => workforceApi.pause(run.id), "已请求暂停")}
                  style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid var(--border,#d1d5db)", background: "transparent", cursor: "pointer" }}
                >
                  暂停
                </button>
              </>
            )}
            {/* paused/interrupted 的续跑入口在 RunDecisionPanel（带原因说明，
                避免与头部条重复渲染同动作按钮） */}
          </div>
        </div>

        {/* ---- 决策面板（服务端授权驱动：批准门/澄清/裁决/挂起续跑） ---- */}
        <RunDecisionPanel run={run} onAct={act} busy={busy} />

        {/* ---- 最终汇总卡 ---- */}
        {run.status === "done" && run.summary && (
          <div className="list-row-card" style={{ marginBottom: 14, borderLeft: "3px solid #16a34a" }}>
            <div style={{ width: "100%" }}>
              <div className="list-row-title" style={{ marginBottom: 6 }}>
                <i className="fa-solid fa-flag-checkered" style={{ marginRight: 6 }} />
                最终交付
              </div>
              <div className="list-row-desc" style={{ whiteSpace: "pre-wrap" }}>
                {run.summary.slice(0, 2000)}
              </div>
            </div>
          </div>
        )}

        {/* ---- DAG 任务树（波次分层 + 节点留痕，RunTaskTree 投影） ---- */}
        <RunTaskTree run={run} />

        {run.source_chat_id && (
          <div className="list-row-desc" style={{ marginTop: 8 }}>
            <Link to={`/chat?chat=${run.source_chat_id}`}>← 返回来源会话</Link>
          </div>
        )}
      </PageShell>
    </div>
  );
}
