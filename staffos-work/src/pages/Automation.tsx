/**
 * Automation — scheduled jobs list (default agent cron plane). Extension
 * design: PageShell + list-row cards with status pills (no antd Table).
 * Project-scoped automations are managed per-project (right config panel).
 */
import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import { useToast } from "../components/Toast";
import { request } from "../api/request";

interface CronJob {
  id: string;
  name: string;
  schedule?: { cron?: string; type?: string };
  enabled?: boolean;
  text?: string;
  meta?: Record<string, unknown>;
}

export default function AutomationPage() {
  const toast = useToast();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<CronJob[] | { jobs?: CronJob[] }>(
        "/crons/jobs",
      );
      setJobs(Array.isArray(data) ? data : (data.jobs ?? []));
    } catch (err) {
      toast.error(`加载自动化失败：${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="view active">
      <PageShell
        title="自动化"
        subtitle="定时任务与自动流程（项目内自动化请在项目配置面板中创建）"
      >
        {loading && <div className="blank-state">加载中…</div>}
        {!loading && jobs.length === 0 && (
          <div className="blank-state">
            <i
              className="fa-regular fa-clock"
              style={{ fontSize: 26, marginBottom: 10 }}
            />
            <div>暂无自动化任务，去项目右栏「自动化」创建第一条吧</div>
          </div>
        )}
        {jobs.map((job) => {
          const scope = (job.meta as { project_id?: string } | undefined)
            ?.project_id;
          return (
            <div key={job.id} className="list-row-card">
              <div className="list-row-main">
                <div
                  className="card-icon"
                  style={{ width: 36, height: 36, fontSize: 14, marginBottom: 0 }}
                >
                  <i className="fa-regular fa-clock" />
                </div>
                <div>
                  <div className="list-row-title">{job.name}</div>
                  <div className="list-row-desc">
                    {job.schedule?.cron ?? "—"}
                    {job.text ? ` · ${job.text.slice(0, 40)}` : ""}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {scope && (
                  <span className="task-status">
                    <i className="fa-solid fa-layer-group" style={{ fontSize: 9 }} />
                    项目
                  </span>
                )}
                <span
                  className={`task-status${job.enabled ? " completed" : ""}`}
                >
                  <div
                    className={`status-dot ${job.enabled ? "dot-green" : "dot-gray"}`}
                  />
                  {job.enabled ? "运行中" : "已暂停"}
                </span>
              </div>
            </div>
          );
        })}
      </PageShell>
    </div>
  );
}
