/**
 * Admin/Teams — team CRUD with member lists (M5).
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminTeamsApi, adminUsersApi } from "../../api/modules/admin";
import type { AdminUserView, TeamRecord } from "../../api/modules/admin";
import styles from "./admin.module.less";

function TeamsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<TeamRecord | "new" | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [teamList, userList] = await Promise.all([
        adminTeamsApi.list(),
        adminUsersApi.list().catch(() => [] as AdminUserView[]),
      ]);
      setTeams(teamList);
      setUsers(userList);
    } catch (err) {
      console.error("Failed to load teams:", err);
      message.error(t("admin.teams.loadFailed", "Failed to load teams"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (team: TeamRecord | "new") => {
    setEditing(team);
    form.setFieldsValue(
      team === "new"
        ? { name: "", members: [], description: "" }
        : {
            name: team.name,
            members: team.members,
            description: team.description,
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      await adminTeamsApi.upsert(values.name, {
        members: values.members ?? [],
        description: values.description ?? "",
      });
      message.success(t("admin.teams.saved", "Team saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (team: TeamRecord) => {
    try {
      await adminTeamsApi.remove(team.name);
      message.success(t("admin.teams.deleted", "Team deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminTeams", "Teams")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.teams.create", "New team")}
          </Button>
        }
      />
      <Table<TeamRecord>
        rowKey="name"
        loading={loading}
        dataSource={teams}
        pagination={false}
        columns={[
          { title: t("admin.teams.name", "Name"), dataIndex: "name" },
          {
            title: t("admin.teams.members", "Members"),
            dataIndex: "members",
            render: (members: string[]) =>
              members.length
                ? members.map((member) => <Tag key={member}>{member}</Tag>)
                : "—",
          },
          {
            title: t("admin.teams.description", "Description"),
            dataIndex: "description",
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.teams.actions", "Actions"),
            key: "actions",
            width: 180,
            render: (_, team) => (
              <>
                <Button size="small" onClick={() => openEditor(team)}>
                  {t("common.edit", "Edit")}
                </Button>
                <Popconfirm
                  title={t("admin.teams.deleteConfirm", "Delete this team?")}
                  onConfirm={() => handleDelete(team)}
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
            ? t("admin.teams.create", "New team")
            : t("admin.teams.edit", "Edit team")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.teams.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input disabled={editing !== "new"} placeholder="core" />
          </Form.Item>
          <Form.Item name="members" label={t("admin.teams.members", "Members")}>
            <Select
              mode="multiple"
              options={users.map((user) => ({
                value: user.username,
                label: user.display_name
                  ? `${user.display_name} (${user.username})`
                  : user.username,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.teams.description", "Description")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default TeamsPage;
