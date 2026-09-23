/**
 * GrantPanel — shared ACL editor for agent/model grants (M5).
 *
 * Semantics (mirrors M4-3 backend): a resource *absent* from the grants
 * table is unrestricted; once a grant exists, only the listed
 * users/roles/teams may use it.
 */
import { useCallback, useEffect, useState } from "react";
import {
  AutoComplete,
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
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  adminGrantsApi,
  adminRolesApi,
  adminTeamsApi,
  adminUsersApi,
} from "../../api/modules/admin";
import type { GrantRecord } from "../../api/modules/admin";
import styles from "./admin.module.less";

interface GrantPanelProps {
  kind: "agent" | "model";
  /** Existing resource ids offered as autocomplete suggestions. */
  resourceOptions: string[];
}

interface GrantRow {
  resource: string;
  grant: GrantRecord;
}

function GrantPanel({ kind, resourceOptions }: GrantPanelProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [rows, setRows] = useState<GrantRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<GrantRow | "new" | null>(null);
  const [userOptions, setUserOptions] = useState<string[]>([]);
  const [roleOptions, setRoleOptions] = useState<string[]>([]);
  const [teamOptions, setTeamOptions] = useState<string[]>([]);
  const [form] = Form.useForm();

  const isAgent = kind === "agent";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const grants = isAgent
        ? await adminGrantsApi.listAgents()
        : await adminGrantsApi.listModels();
      setRows(
        Object.entries(grants).map(([resource, grant]) => ({
          resource,
          grant,
        })),
      );
    } catch (err) {
      console.error("Failed to load grants:", err);
      message.error(t("admin.grants.loadFailed", "Failed to load grants"));
    } finally {
      setLoading(false);
    }
  }, [isAgent, message, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    adminUsersApi
      .list()
      .then((users) => setUserOptions(users.map((user) => user.username)))
      .catch(() => setUserOptions([]));
    adminRolesApi
      .list()
      .then((roles) => setRoleOptions(roles.map((role) => role.name)))
      .catch(() => setRoleOptions([]));
    adminTeamsApi
      .list()
      .then((teams) => setTeamOptions(teams.map((team) => team.name)))
      .catch(() => setTeamOptions([]));
  }, []);

  const openEditor = (row: GrantRow | "new") => {
    setEditing(row);
    form.setFieldsValue(
      row === "new"
        ? { resource: "", users: [], roles: [], teams: [], description: "" }
        : {
            resource: row.resource,
            users: row.grant.users,
            roles: row.grant.roles,
            teams: row.grant.teams,
            description: row.grant.description,
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const body = {
      users: values.users ?? [],
      roles: values.roles ?? [],
      teams: values.teams ?? [],
      description: values.description ?? "",
    };
    try {
      if (isAgent) {
        await adminGrantsApi.putAgent(values.resource, body);
      } else {
        await adminGrantsApi.putModel(values.resource, body);
      }
      message.success(t("admin.grants.saved", "Grant saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (row: GrantRow) => {
    try {
      if (isAgent) {
        await adminGrantsApi.removeAgent(row.resource);
      } else {
        await adminGrantsApi.removeModel(row.resource);
      }
      message.success(t("admin.grants.deleted", "Grant removed"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <>
      <div className={styles.hint} style={{ marginBottom: 12 }}>
        {t(
          "admin.grants.unrestrictedHint",
          "Resources without a grant entry stay unrestricted; adding an entry restricts use to the listed users/roles/teams.",
        )}
      </div>
      <div style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={() => openEditor("new")}>
          {t("admin.grants.create", "New grant")}
        </Button>
      </div>
      <Table<GrantRow>
        rowKey="resource"
        loading={loading}
        dataSource={rows}
        pagination={false}
        columns={[
          {
            title: isAgent
              ? t("admin.grants.agent", "Agent")
              : t("admin.grants.model", "Model"),
            dataIndex: "resource",
          },
          {
            title: t("admin.grants.allowed", "Allowed"),
            key: "allowed",
            render: (_, row) => (
              <>
                {row.grant.roles.map((role) => (
                  <Tag key={`r-${role}`} color="geekblue">
                    {t("admin.grants.rolePrefix", "role")}:{role}
                  </Tag>
                ))}
                {row.grant.users.map((user) => (
                  <Tag key={`u-${user}`} color="green">
                    {t("admin.grants.userPrefix", "user")}:{user}
                  </Tag>
                ))}
                {row.grant.teams.map((team) => (
                  <Tag key={`t-${team}`} color="orange">
                    {t("admin.grants.teamPrefix", "team")}:{team}
                  </Tag>
                ))}
              </>
            ),
          },
          {
            title: t("admin.grants.description", "Description"),
            dataIndex: ["grant", "description"],
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.grants.actions", "Actions"),
            key: "actions",
            width: 180,
            render: (_, row) => (
              <>
                <Button size="small" onClick={() => openEditor(row)}>
                  {t("common.edit", "Edit")}
                </Button>
                <Popconfirm
                  title={t(
                    "admin.grants.deleteConfirm",
                    "Remove this grant? The resource becomes unrestricted.",
                  )}
                  onConfirm={() => handleDelete(row)}
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
            ? t("admin.grants.create", "New grant")
            : t("admin.grants.edit", "Edit grant")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="resource"
            label={
              isAgent
                ? t("admin.grants.agent", "Agent")
                : t("admin.grants.model", "Model")
            }
            rules={[{ required: true }]}
          >
            <AutoComplete
              disabled={editing !== "new"}
              options={resourceOptions.map((value) => ({ value }))}
              placeholder={
                isAgent ? "default" : "provider:model (e.g. dashscope:qwen-max)"
              }
            />
          </Form.Item>
          <Form.Item name="roles" label={t("admin.grants.roles", "Roles")}>
            <Select
              mode="multiple"
              options={roleOptions.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
          <Form.Item name="users" label={t("admin.grants.users", "Users")}>
            <Select
              mode="multiple"
              options={userOptions.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
          <Form.Item name="teams" label={t("admin.grants.teams", "Teams")}>
            <Select
              mode="multiple"
              options={teamOptions.map((value) => ({ value, label: value }))}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.grants.description", "Description")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default GrantPanel;
