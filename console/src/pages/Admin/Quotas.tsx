/**
 * Admin/Quotas — LLM quota rules (M5, wraps M4-4 backend).
 *
 * window="minute" counts requests per fixed minute; window="day" counts
 * tokens per UTC day (cost circuit-breaker).
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminQuotasApi } from "../../api/modules/admin";
import type { QuotaRule } from "../../api/modules/admin";
import styles from "./admin.module.less";

const ruleKey = (rule: QuotaRule) =>
  `${rule.subject_type}:${rule.subject}:${rule.model}:${rule.window}`;

function QuotasPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [rules, setRules] = useState<QuotaRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<QuotaRule | "new" | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await adminQuotasApi.list());
    } catch (err) {
      console.error("Failed to load quotas:", err);
      message.error(t("admin.quotas.loadFailed", "Failed to load quotas"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (rule: QuotaRule | "new") => {
    setEditing(rule);
    form.setFieldsValue(
      rule === "new"
        ? {
            subject_type: "user",
            subject: "",
            model: "*",
            window: "day",
            limit: 100000,
            description: "",
          }
        : { ...rule },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      await adminQuotasApi.upsert(values);
      message.success(t("admin.quotas.saved", "Quota saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (rule: QuotaRule) => {
    try {
      await adminQuotasApi.remove(rule);
      message.success(t("admin.quotas.deleted", "Quota deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminQuotas", "Quotas")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.quotas.create", "New quota")}
          </Button>
        }
      />
      <div className={styles.hint} style={{ marginBottom: 12 }}>
        {t(
          "admin.quotas.hint",
          "minute = requests per minute; day = tokens per UTC day (cost breaker). Exceeding a rule fails the LLM call with a rate-limit signal.",
        )}
      </div>
      <Table<QuotaRule>
        rowKey={ruleKey}
        loading={loading}
        dataSource={rules}
        pagination={false}
        columns={[
          {
            title: t("admin.quotas.subjectType", "Subject type"),
            dataIndex: "subject_type",
            width: 130,
            render: (v: string) => <Tag color="geekblue">{v}</Tag>,
          },
          { title: t("admin.quotas.subject", "Subject"), dataIndex: "subject" },
          { title: t("admin.quotas.model", "Model"), dataIndex: "model" },
          {
            title: t("admin.quotas.window", "Window"),
            dataIndex: "window",
            width: 110,
            render: (v: string) => <Tag>{v}</Tag>,
          },
          {
            title: t("admin.quotas.limit", "Limit"),
            dataIndex: "limit",
            width: 120,
            render: (v: number) => v.toLocaleString(),
          },
          {
            title: t("admin.quotas.description", "Description"),
            dataIndex: "description",
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.quotas.actions", "Actions"),
            key: "actions",
            width: 180,
            render: (_, rule) => (
              <>
                <Button size="small" onClick={() => openEditor(rule)}>
                  {t("common.edit", "Edit")}
                </Button>
                <Popconfirm
                  title={t("admin.quotas.deleteConfirm", "Delete this quota?")}
                  onConfirm={() => handleDelete(rule)}
                >
                  <Button size="small" danger style={{ marginLeft: 8 }}>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              </>
            ),
          },
        ]}
      />

      <Modal
        title={
          editing === "new"
            ? t("admin.quotas.create", "New quota")
            : t("admin.quotas.edit", "Edit quota")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="subject_type"
            label={t("admin.quotas.subjectType", "Subject type")}
            rules={[{ required: true }]}
          >
            <Select
              disabled={editing !== "new"}
              options={[
                { value: "user", label: "user" },
                { value: "team", label: "team" },
                { value: "agent", label: "agent" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="subject"
            label={t("admin.quotas.subject", "Subject")}
            rules={[{ required: true }]}
            extra={t(
              "admin.quotas.subjectHint",
              "Username, team name, or agent id depending on the subject type.",
            )}
          >
            <Input disabled={editing !== "new"} />
          </Form.Item>
          <Form.Item name="model" label={t("admin.quotas.model", "Model")}>
            <Input disabled={editing !== "new"} placeholder="* or provider:model" />
          </Form.Item>
          <Form.Item name="window" label={t("admin.quotas.window", "Window")}>
            <Select
              disabled={editing !== "new"}
              options={[
                { value: "minute", label: "minute" },
                { value: "day", label: "day" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="limit"
            label={t("admin.quotas.limit", "Limit")}
            rules={[{ required: true }]}
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.quotas.description", "Description")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default QuotasPage;
