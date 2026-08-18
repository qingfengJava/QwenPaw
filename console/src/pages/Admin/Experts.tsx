/**
 * Admin/Experts — expert lifecycle: draft → publish → archive
 * (XianWork Phase 3). The draft `agent_spec` is edited as JSON in the
 * first release; full Agent-form parity is a follow-up enhancement.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Divider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminExpertsApi } from "../../api/modules/admin";
import type { ExpertRecord } from "../../api/modules/admin";
import {
  SampleTasksEditor,
  ShowcaseEditor,
  normalizeShowcase,
} from "./OperationsFields";
import styles from "./admin.module.less";

const STATUS_COLOR: Record<string, string> = {
  draft: "default",
  published: "green",
  archived: "red",
};

function ExpertsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [experts, setExperts] = useState<ExpertRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ExpertRecord | "new" | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setExperts(await adminExpertsApi.list());
    } catch (err) {
      message.error(
        t("admin.experts.loadFailed", "Failed to load experts"),
      );
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (expert: ExpertRecord | "new") => {
    setEditing(expert);
    form.setFieldsValue(
      expert === "new"
        ? {
            name: "",
            icon: "",
            description: "",
            agent_spec: "{}",
            sample_tasks: [],
            showcase: [],
          }
        : {
            name: expert.name,
            icon: expert.icon,
            description: expert.description,
            agent_spec: JSON.stringify(expert.agent_spec, null, 2),
            sample_tasks: expert.sample_tasks ?? [],
            // tags 回填为逗号串（编辑器输入形态）
            showcase: (expert.showcase ?? []).map((c) => ({
              ...c,
              tags: (c.tags ?? []).join(","),
            })),
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    let spec: Record<string, unknown>;
    try {
      spec = JSON.parse(values.agent_spec || "{}");
    } catch {
      message.error(
        t("admin.experts.badJson", "agent_spec must be valid JSON"),
      );
      return;
    }
    const sampleTasks = (values.sample_tasks ?? []).filter(
      (item: { title?: string; prompt?: string }) =>
        (item.title ?? "").trim() && (item.prompt ?? "").trim(),
    );
    const showcase = normalizeShowcase(values.showcase).filter(
      (item) => item.title.trim() && item.desc.trim(),
    );
    try {
      if (editing === "new") {
        await adminExpertsApi.create({
          name: values.name,
          icon: values.icon ?? "",
          description: values.description ?? "",
          agent_spec: spec,
          sample_tasks: sampleTasks,
          showcase,
        });
      } else if (editing) {
        await adminExpertsApi.update(editing.id, {
          name: values.name,
          icon: values.icon,
          description: values.description,
          agent_spec: spec,
          sample_tasks: sampleTasks,
          showcase,
        });
      }
      message.success(t("admin.experts.saved", "Expert saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handlePublish = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.publish(expert.id);
      message.success(
        t("admin.experts.published", "Expert published to XianWork"),
      );
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleArchive = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.archive(expert.id);
      message.success(t("admin.experts.archived", "Expert archived"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.remove(expert.id);
      message.success(t("admin.experts.deleted", "Draft deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminExperts", "Experts")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.experts.create", "New expert")}
          </Button>
        }
      />
      <Table<ExpertRecord>
        rowKey="id"
        loading={loading}
        dataSource={experts}
        pagination={false}
        columns={[
          { title: t("admin.experts.name", "Name"), dataIndex: "name" },
          {
            title: t("admin.experts.description", "Description"),
            dataIndex: "description",
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.experts.status", "Status"),
            dataIndex: "status",
            width: 110,
            render: (status: string) => (
              <Tag color={STATUS_COLOR[status]}>{status}</Tag>
            ),
          },
          {
            title: "v",
            dataIndex: "version",
            width: 60,
          },
          {
            title: t("admin.experts.actions", "Actions"),
            key: "actions",
            width: 280,
            render: (_, expert) => (
              <Space>
                <Button size="small" onClick={() => openEditor(expert)}>
                  {t("common.edit", "Edit")}
                </Button>
                {expert.status !== "archived" && (
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() => handlePublish(expert)}
                  >
                    {t("admin.experts.publish", "Publish")}
                  </Button>
                )}
                {expert.status === "published" && (
                  <Button size="small" onClick={() => handleArchive(expert)}>
                    {t("admin.experts.archive", "Archive")}
                  </Button>
                )}
                {expert.status === "draft" && (
                  <Popconfirm
                    title={t(
                      "admin.experts.deleteConfirm",
                      "Delete this draft?",
                    )}
                    onConfirm={() => handleDelete(expert)}
                  >
                    <Button size="small" danger>
                      {t("common.delete", "Delete")}
                    </Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={
          editing === "new"
            ? t("admin.experts.create", "New expert")
            : t("admin.experts.edit", "Edit expert")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.experts.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="icon" label={t("admin.experts.icon", "Icon")}>
            <Input placeholder="🧑‍💼" />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.experts.description", "Description")}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="agent_spec"
            label={t(
              "admin.experts.spec",
              "Agent spec (agent.json-compatible JSON)",
            )}
            rules={[
              {
                validator: (_, value) => {
                  if (!value) return Promise.resolve();
                  try {
                    JSON.parse(value);
                    return Promise.resolve();
                  } catch {
                    return Promise.reject(new Error("invalid JSON"));
                  }
                },
              },
            ]}
          >
            <Input.TextArea rows={10} style={{ fontFamily: "monospace" }} />
          </Form.Item>
          <Divider orientation="left" plain>
            {t("admin.ops.section", "运营位（专家帮你做 / 使用案例）")}
          </Divider>
          <Form.Item
            label={t(
              "admin.ops.tasks",
              "任务模板（详情页「专家帮你做」，点击即以提示词召唤）",
            )}
          >
            <SampleTasksEditor />
          </Form.Item>
          <Form.Item
            label={t("admin.ops.cases", "使用案例（静态运营位）")}
          >
            <ShowcaseEditor />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExpertsPage;
