/**
 * Admin/ExpertTeams — multi-expert orchestration: ordered members,
 * router/pipeline mode, publish to XianWork (Phase 3).
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  adminExpertTeamsApi,
  adminExpertsApi,
} from "../../api/modules/admin";
import type {
  ExpertRecord,
  ExpertTeamRecord,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

function ExpertTeamsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [teams, setTeams] = useState<ExpertTeamRecord[]>([]);
  const [experts, setExperts] = useState<ExpertRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ExpertTeamRecord | "new" | null>(
    null,
  );
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [teamList, expertList] = await Promise.all([
        adminExpertTeamsApi.list(),
        adminExpertsApi.list("published").catch(() => []),
      ]);
      setTeams(teamList);
      setExperts(expertList);
    } catch (err) {
      message.error(t("admin.teamsX.loadFailed", "Failed to load teams"));
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (team: ExpertTeamRecord | "new") => {
    setEditing(team);
    form.setFieldsValue(
      team === "new"
        ? {
            name: "",
            description: "",
            mode: "router",
            router_prompt: "",
            members: [],
          }
        : {
            name: team.name,
            description: team.description,
            mode: team.mode,
            router_prompt: team.router_prompt,
            members: team.members.map((m) => m.expert_id),
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const memberIds: string[] = values.members ?? [];
    const members = memberIds.map((expert_id, index) => ({
      expert_id,
      seq: index,
    }));
    try {
      if (editing === "new") {
        await adminExpertTeamsApi.create({
          name: values.name,
          description: values.description ?? "",
          mode: values.mode,
          router_prompt: values.router_prompt ?? "",
          members,
        });
      } else if (editing) {
        await adminExpertTeamsApi.update(editing.id, {
          name: values.name,
          description: values.description,
          mode: values.mode,
          router_prompt: values.router_prompt,
          members,
        });
      }
      message.success(t("admin.teamsX.saved", "Team saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handlePublish = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.publish(team.id);
      message.success(
        t("admin.teamsX.published", "Team published to XianWork"),
      );
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleArchive = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.archive(team.id);
      message.success(t("admin.teamsX.archived", "Team archived"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.remove(team.id);
      message.success(t("admin.teamsX.deleted", "Team deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const expertName = (id: string) =>
    experts.find((e) => e.id === id)?.name ?? id;

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminExpertTeams", "Expert Teams")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.teamsX.create", "New expert team")}
          </Button>
        }
      />
      <Table<ExpertTeamRecord>
        rowKey="id"
        loading={loading}
        dataSource={teams}
        pagination={false}
        columns={[
          { title: t("admin.teamsX.name", "Name"), dataIndex: "name" },
          {
            title: t("admin.teamsX.mode", "Mode"),
            dataIndex: "mode",
            width: 110,
            render: (mode: string) => (
              <Tag color={mode === "pipeline" ? "blue" : "purple"}>
                {mode}
              </Tag>
            ),
          },
          {
            title: t("admin.teamsX.members", "Members"),
            dataIndex: "members",
            render: (members: ExpertTeamRecord["members"]) =>
              members.length
                ? members.map((m) => (
                    <Tag key={m.expert_id}>{expertName(m.expert_id)}</Tag>
                  ))
                : "—",
          },
          {
            title: t("admin.teamsX.status", "Status"),
            dataIndex: "status",
            width: 110,
            render: (status: string) => (
              <Tag
                color={
                  status === "published"
                    ? "green"
                    : status === "archived"
                      ? "red"
                      : "default"
                }
              >
                {status}
              </Tag>
            ),
          },
          {
            title: t("admin.teamsX.actions", "Actions"),
            key: "actions",
            width: 280,
            render: (_, team) => (
              <Space>
                <Button size="small" onClick={() => openEditor(team)}>
                  {t("common.edit", "Edit")}
                </Button>
                {team.status !== "archived" && (
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() => handlePublish(team)}
                  >
                    {t("admin.teamsX.publish", "Publish")}
                  </Button>
                )}
                {team.status === "published" && (
                  <Button size="small" onClick={() => handleArchive(team)}>
                    {t("admin.teamsX.archive", "Archive")}
                  </Button>
                )}
                {team.status === "draft" && (
                  <Popconfirm
                    title={t(
                      "admin.teamsX.deleteConfirm",
                      "Delete this team?",
                    )}
                    onConfirm={() => handleDelete(team)}
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
            ? t("admin.teamsX.create", "New expert team")
            : t("admin.teamsX.edit", "Edit expert team")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        width={620}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.teamsX.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.teamsX.description", "Description")}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="mode"
            label={t("admin.teamsX.mode", "Orchestration mode")}
          >
            <Select
              options={[
                {
                  value: "router",
                  label: t(
                    "admin.teamsX.modeRouter",
                    "router — pick the best member per turn",
                  ),
                },
                {
                  value: "pipeline",
                  label: t(
                    "admin.teamsX.modePipeline",
                    "pipeline — members run in order (max 3)",
                  ),
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="members"
            label={t(
              "admin.teamsX.members",
              "Member experts (published only, ordered)",
            )}
          >
            <Select
              mode="multiple"
              options={experts.map((e) => ({
                value: e.id,
                label: e.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="router_prompt"
            label={t(
              "admin.teamsX.routerPrompt",
              "Routing guidance (supervisor prompt)",
            )}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExpertTeamsPage;
