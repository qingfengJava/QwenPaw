/**
 * Admin/Audit — governance audit log query (M5, wraps M4-6 backend).
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Input, Select, Table, Tag } from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminAuditApi } from "../../api/modules/admin";
import type { AuditEventView } from "../../api/modules/admin";
import styles from "./admin.module.less";

const PAGE_SIZE = 50;

function AuditPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [events, setEvents] = useState<AuditEventView[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [toolName, setToolName] = useState("");
  const [decision, setDecision] = useState<string>("");

  const load = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      try {
        const result = await adminAuditApi.query({
          agent_id: agentId || undefined,
          tool_name: toolName || undefined,
          decision: decision || undefined,
          limit: PAGE_SIZE,
          offset: (targetPage - 1) * PAGE_SIZE,
        });
        setEvents(result.events);
        setTotal(result.total);
      } catch (err) {
        console.error("Failed to load audit events:", err);
        message.error(t("admin.audit.loadFailed", "Failed to load audit log"));
      } finally {
        setLoading(false);
      }
    },
    [agentId, toolName, decision, message, t],
  );

  useEffect(() => {
    load(page);
  }, [load, page]);

  const decisionColor = (value: string) => {
    if (value === "allow" || value === "allowed") return "green";
    if (value === "deny" || value === "denied" || value === "block") {
      return "red";
    }
    return "orange";
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminAudit", "Audit Log")}
      />
      <div className={styles.toolbar}>
        <Input
          placeholder={t("admin.audit.agentId", "Agent id")}
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          style={{ width: 180 }}
          allowClear
        />
        <Input
          placeholder={t("admin.audit.toolName", "Tool name")}
          value={toolName}
          onChange={(e) => setToolName(e.target.value)}
          style={{ width: 180 }}
          allowClear
        />
        <Select
          placeholder={t("admin.audit.decision", "Decision")}
          value={decision || undefined}
          onChange={(value) => setDecision(value ?? "")}
          style={{ width: 140 }}
          allowClear
          options={[
            { value: "allow", label: "allow" },
            { value: "deny", label: "deny" },
          ]}
        />
        <Button
          type="primary"
          onClick={() => {
            setPage(1);
            load(1);
          }}
        >
          {t("admin.audit.search", "Search")}
        </Button>
      </div>
      <Table<AuditEventView>
        rowKey={(row) => `${row.ts}-${row.session_id}-${row.tool_name}`}
        loading={loading}
        dataSource={events}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showSizeChanger: false,
        }}
        columns={[
          {
            title: t("admin.audit.time", "Time"),
            dataIndex: "ts",
            width: 170,
            render: (ts: number) =>
              dayjs(ts * 1000).format("YYYY-MM-DD HH:mm:ss"),
          },
          {
            title: t("admin.audit.actor", "Actor"),
            dataIndex: "actor_id",
            width: 120,
            render: (v: string) => v || "—",
          },
          { title: t("admin.audit.agent", "Agent"), dataIndex: "agent_id" },
          { title: t("admin.audit.tool", "Tool"), dataIndex: "tool_name" },
          {
            title: t("admin.audit.target", "Target"),
            dataIndex: "target",
            ellipsis: true,
          },
          {
            title: t("admin.audit.decision", "Decision"),
            dataIndex: "decision",
            width: 100,
            render: (v: string) => <Tag color={decisionColor(v)}>{v}</Tag>,
          },
          {
            title: t("admin.audit.reason", "Reason"),
            dataIndex: "reason",
            ellipsis: true,
            render: (v: string) => v || "—",
          },
        ]}
      />
    </div>
  );
}

export default AuditPage;
