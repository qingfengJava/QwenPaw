/**
 * Admin/Roles — RBAC role CRUD (M5).
 *
 * Built-in roles (platform_admin / team_lead / employee) are re-seeded by
 * the backend on every load and cannot be edited here; custom roles map to
 * `permission = resource:action` strings.
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
import { adminRolesApi } from "../../api/modules/admin";
import type { RoleRecord } from "../../api/modules/admin";
import styles from "./admin.module.less";

/** Permissions known to the M4 backend; free-form entries are allowed. */
const KNOWN_PERMISSIONS = [
  "*",
  "agent:use",
  "agent:manage",
  "agent:*",
  "kb:read",
  "kb:write",
  "kb:*",
  "model:invoke",
  "model:manage",
  "model:*",
  "admin:users",
  "admin:roles",
  "admin:audit",
  "admin:quotas",
  "admin:kb",
  "admin:*",
];

function RolesPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<RoleRecord | "new" | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRoles(await adminRolesApi.list());
    } catch (err) {
      console.error("Failed to load roles:", err);
      message.error(t("admin.roles.loadFailed", "Failed to load roles"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (role: RoleRecord | "new") => {
    setEditing(role);
    if (role === "new") {
      form.setFieldsValue({ name: "", permissions: [], description: "" });
    } else {
      form.setFieldsValue({
        name: role.name,
        permissions: role.permissions,
        description: role.description,
      });
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      await adminRolesApi.upsert(values.name, {
        permissions: values.permissions ?? [],
        description: values.description ?? "",
      });
      message.success(t("admin.roles.saved", "Role saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (role: RoleRecord) => {
    try {
      await adminRolesApi.remove(role.name);
      message.success(t("admin.roles.deleted", "Role deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminRoles", "Roles")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.roles.create", "New role")}
          </Button>
        }
      />
      <Table<RoleRecord>
        rowKey="name"
        loading={loading}
        dataSource={roles}
        pagination={false}
        columns={[
          {
            title: t("admin.roles.name", "Name"),
            dataIndex: "name",
            render: (name: string, role) => (
              <>
                {name}
                {role.builtin ? (
                  <Tag style={{ marginLeft: 8 }} color="blue">
                    {t("admin.roles.builtin", "builtin")}
                  </Tag>
                ) : null}
              </>
            ),
          },
          {
            title: t("admin.roles.permissions", "Permissions"),
            dataIndex: "permissions",
            render: (permissions: string[]) =>
              permissions.map((perm) => <Tag key={perm}>{perm}</Tag>),
          },
          {
            title: t("admin.roles.description", "Description"),
            dataIndex: "description",
            render: (v: string) => v || "—",
          },
          {
            title: t("admin.roles.actions", "Actions"),
            key: "actions",
            width: 180,
            render: (_, role) =>
              role.builtin ? null : (
                <>
                  <Button size="small" onClick={() => openEditor(role)}>
                    {t("common.edit", "Edit")}
                  </Button>
                  <Popconfirm
                    title={t("admin.roles.deleteConfirm", "Delete this role?")}
                    onConfirm={() => handleDelete(role)}
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
            ? t("admin.roles.create", "New role")
            : t("admin.roles.edit", "Edit role")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.roles.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input disabled={editing !== "new"} placeholder="support_lead" />
          </Form.Item>
          <Form.Item
            name="permissions"
            label={t("admin.roles.permissions", "Permissions")}
            extra={t(
              "admin.roles.permissionsHint",
              "resource:action; '*' or 'resource:*' wildcards allowed",
            )}
          >
            <Select
              mode="tags"
              options={KNOWN_PERMISSIONS.map((perm) => ({
                value: perm,
                label: perm,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label={t("admin.roles.description", "Description")}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default RolesPage;
