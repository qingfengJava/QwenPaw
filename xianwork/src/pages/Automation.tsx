/**
 * Automation — cron jobs list (reuses /api/crons; personal-scope in the
 * first release, project-scoped cron is a follow-up).
 */
import { useCallback, useEffect, useState } from "react";
import { message, Table, Tag } from "antd";
import { request } from "../api/request";

interface CronJob {
  id: string;
  name: string;
  schedule?: string;
  enabled?: boolean;
  description?: string;
}

export default function AutomationPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<
        CronJob[] | { jobs?: CronJob[] }
      >("/crons");
      setJobs(Array.isArray(data) ? data : (data.jobs ?? []));
    } catch (err) {
      message.error(`加载自动化失败：${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="xian-page">
      <div className="xian-page-title">自动化</div>
      <div className="xian-page-sub">
        定时任务与自动流程（如「每天 09:00 生成昨日 AI 资讯总结」）
      </div>
      <Table<CronJob>
        rowKey="id"
        loading={loading}
        dataSource={jobs}
        pagination={false}
        columns={[
          { title: "名称", dataIndex: "name" },
          {
            title: "计划",
            dataIndex: "schedule",
            render: (v: string) => <Tag>{v || "—"}</Tag>,
          },
          {
            title: "描述",
            dataIndex: "description",
            render: (v: string) => v || "—",
          },
        ]}
      />
    </div>
  );
}
