/**
 * Admin/Users — account fleet management (M5).
 *
 * Covers the `/admin/users` endpoints: create, edit (flat role / display
 * name / disabled), password reset, and RBAC role grants per user.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Switch,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { HasPerm } from "@/components/HasPerm";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminUsersApi, adminRolesApi } from "../../api/modules/admin";
import type {
  AdminUserView,
  RoleRecord,
  IdentityBindingView,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

// 常见渠道候选（仍可手输其他值）；与后端 channel_id 命名对齐。
const CHANNEL_OPTIONS = [
  { value: "wechat", label: "wechat" },
  { value: "wecom", label: "wecom" },
  { value: "dingtalk", label: "dingtalk" },
  { value: "qq", label: "qq" },
  { value: "feishu", label: "feishu" },
];

function UsersPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [bindings, setBindings] = useState<IdentityBindingView[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [bindOpen, setBindOpen] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<string | null>(null);
  const [createForm] = Form.useForm();
  const [bindForm] = Form.useForm();
  const [passwordForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [userList, roleList, bindingList] = await Promise.all([
        adminUsersApi.list(),
        adminRolesApi.list().catch(() => [] as RoleRecord[]),
        adminUsersApi.listIdentityBindings().catch(() => [] as IdentityBindingView[]),
      ]);
      setUsers(userList);
      setRoles(roleList);
      setBindings(bindingList);
    } catch (err) {
      console.error("Failed to load users:", err);
      message.error(t("admin.users.loadFailed", "Failed to load users"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    try {
      await adminUsersApi.create(values);
      message.success(t("admin.users.created", "User created"));
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleToggleDisabled = async (user: AdminUserView) => {
    try {
      await adminUsersApi.update(user.username, { disabled: !user.disabled });
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleFlatRoleChange = async (user: AdminUserView, role: string) => {
    try {
      await adminUsersApi.update(user.username, { role });
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleGrantRole = async (user: AdminUserView, role: string) => {
    try {
      await adminUsersApi.grantRole(user.username, role);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleRevokeRole = async (user: AdminUserView, role: string) => {
    try {
      await adminUsersApi.revokeRole(user.username, role);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleResetPassword = async () => {
    const values = await passwordForm.validateFields();
    if (!passwordTarget) return;
    try {
      await adminUsersApi.setPassword(passwordTarget, values.password);
      message.success(t("admin.users.passwordReset", "Password updated"));
      setPasswordTarget(null);
      passwordForm.resetFields();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleCreateBinding = async () => {
    const values = await bindForm.validateFields();
    try {
      await adminUsersApi.createIdentityBinding(values);
      message.success(t("admin.users.bindingCreated", "Binding created"));
      setBindOpen(false);
      bindForm.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDeleteBinding = async (binding: IdentityBindingView) => {
    try {
      await adminUsersApi.deleteIdentityBinding(
        binding.channel,
        binding.external_user_id,
      );
      message.success(t("admin.users.bindingDeleted", "Binding removed"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminUsers", "Users")}
        extra={
          <HasPerm code="admin:usersCreate">
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              {t("admin.users.create", "New user")}
            </Button>
          </HasPerm>
        }
      />
      <Table<AdminUserView>
        rowKey="username"
        loading={loading}
        dataSource={users}
        pagination={false}
        columns={[
          {
            title: t("admin.users.username", "Username"),
            dataIndex: "username",
          },
          {
            title: t("admin.users.displayName", "Display name"),
            dataIndex: "display_name",
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.users.flatRole", "Role"),
            dataIndex: "role",
            render: (role: string, user) => (
              <Select
                size="small"
                value={role}
                style={{ width: 120 }}
                onChange={(next) => handleFlatRoleChange(user, next)}
                options={[
                  { value: "admin", label: "admin" },
                  { value: "employee", label: "employee" },
                ]}
              />
            ),
          },
          {
            title: t("admin.users.rbacRoles", "RBAC roles"),
            dataIndex: "rbac_roles",
            render: (rbacRoles: string[], user) => (
              <>
                {rbacRoles.map((role) => (
                  <Tag
                    key={role}
                    closable
                    onClose={(e) => {
                      e.preventDefault();
                      handleRevokeRole(user, role);
                    }}
                  >
                    {role}
                  </Tag>
                ))}
                <Select<string | null>
                  size="small"
                  placeholder={t("admin.users.grantRole", "+ role")}
                  style={{ width: 130 }}
                  value={null}
                  onChange={(role) => {
                    if (role) handleGrantRole(user, role);
                  }}
                  options={roles
                    .filter((r) => !user.rbac_roles.includes(r.name))
                    .map((r) => ({ value: r.name, label: r.name }))}
                />
              </>
            ),
          },
          {
            title: t("admin.users.teams", "Teams"),
            dataIndex: "teams",
            render: (teams: string[]) =>
              teams.length ? teams.map((team) => <Tag key={team}>{team}</Tag>) : "—",
          },
          {
            title: t("admin.users.disabled", "Disabled"),
            dataIndex: "disabled",
            width: 100,
            render: (disabled: boolean, user) => (
              <Switch
                size="small"
                checked={disabled}
                onChange={() => handleToggleDisabled(user)}
              />
            ),
          },
          {
            title: t("admin.users.actions", "Actions"),
            key: "actions",
            width: 150,
            render: (_, user) => (
              <HasPerm code="admin:usersResetPwd">
                <Popconfirm
                  title={t(
                    "admin.users.resetPasswordConfirm",
                    "Reset this user's password?",
                  )}
                  onConfirm={() => setPasswordTarget(user.username)}
                >
                  <Button size="small">
                    {t("admin.users.resetPassword", "Reset password")}
                  </Button>
                </Popconfirm>
              </HasPerm>
            ),
          },
        ]}
      />

      <Modal
        title={t("admin.users.create", "New user")}
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="username"
            label={t("admin.users.username", "Username")}
            rules={[{ required: true }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label={t("admin.users.password", "Password")}
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="display_name" label={t("admin.users.displayName", "Display name")}>
            <Input />
          </Form.Item>
          <Form.Item
            name="role"
            label={t("admin.users.flatRole", "Role")}
            initialValue="employee"
          >
            <Select
              options={[
                { value: "employee", label: "employee" },
                { value: "admin", label: "admin" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("admin.users.resetPassword", "Reset password")}
        open={passwordTarget !== null}
        onOk={handleResetPassword}
        onCancel={() => setPasswordTarget(null)}
        destroyOnHidden
      >
        <Form form={passwordForm} layout="vertical" preserve={false}>
          <Form.Item
            name="password"
            label={t("admin.users.newPassword", "New password")}
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <Card
        style={{ marginTop: 24 }}
        title={t("admin.users.bindingsTitle", "Channel identity bindings")}
        extra={
          <Button size="small" onClick={() => setBindOpen(true)}>
            {t("admin.users.bindingsAdd", "New binding")}
          </Button>
        }
      >
        <Table<IdentityBindingView>
          rowKey={(row) => `${row.channel}:${row.external_user_id}`}
          loading={loading}
          dataSource={bindings}
          pagination={false}
          size="small"
          locale={{
            emptyText: t(
              "admin.users.bindingsEmpty",
              "No channel identities bound to accounts yet",
            ),
          }}
          columns={[
            {
              title: t("admin.users.bindingsChannel", "Channel"),
              dataIndex: "channel",
              render: (channel: string) => <Tag>{channel}</Tag>,
            },
            {
              title: t("admin.users.bindingsExternal", "External user id"),
              dataIndex: "external_user_id",
            },
            {
              title: t("admin.users.bindingsAccount", "Account"),
              dataIndex: "username",
            },
            {
              title: t("admin.users.actions", "Actions"),
              key: "actions",
              width: 120,
              render: (_, binding) => (
                <Popconfirm
                  title={t(
                    "admin.users.bindingDeleteConfirm",
                    "Remove this binding?",
                  )}
                  onConfirm={() => handleDeleteBinding(binding)}
                >
                  <Button size="small" danger>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={t("admin.users.bindingsAdd", "New binding")}
        open={bindOpen}
        onOk={handleCreateBinding}
        onCancel={() => setBindOpen(false)}
        destroyOnHidden
      >
        <Form form={bindForm} layout="vertical" preserve={false}>
          <Form.Item
            name="channel"
            label={t("admin.users.bindingsChannel", "Channel")}
            rules={[{ required: true }]}
          >
            <Select
              showSearch
              options={CHANNEL_OPTIONS}
              placeholder={t(
                "admin.users.bindingsChannelPlaceholder",
                "Select or type a channel",
              )}
            />
          </Form.Item>
          <Form.Item
            name="external_user_id"
            label={t("admin.users.bindingsExternal", "External user id")}
            rules={[{ required: true }]}
          >
            <Input placeholder="openid / userid" />
          </Form.Item>
          <Form.Item
            name="username"
            label={t("admin.users.bindingsAccount", "Account")}
            rules={[{ required: true }]}
          >
            <Select
              showSearch
              options={users.map((u) => ({
                value: u.username,
                label: u.display_name
                  ? `${u.display_name} (${u.username})`
                  : u.username,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default UsersPage;
