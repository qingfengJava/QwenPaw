/**
 * Admin/Users — account fleet management (M5).
 *
 * Covers the `/admin/users` endpoints: create, edit (flat role / display
 * name / disabled), password reset, and RBAC role grants per user.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
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
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminUsersApi, adminRolesApi } from "../../api/modules/admin";
import type { AdminUserView, RoleRecord } from "../../api/modules/admin";
import styles from "./admin.module.less";

function UsersPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<string | null>(null);
  const [createForm] = Form.useForm();
  const [passwordForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [userList, roleList] = await Promise.all([
        adminUsersApi.list(),
        adminRolesApi.list().catch(() => [] as RoleRecord[]),
      ]);
      setUsers(userList);
      setRoles(roleList);
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

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminUsers", "Users")}
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            {t("admin.users.create", "New user")}
          </Button>
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
    </div>
  );
}

export default UsersPage;
