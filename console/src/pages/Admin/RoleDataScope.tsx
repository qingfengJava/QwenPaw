/**
 * RoleDataScope — Modal for managing data scope rules per role (M7 PG-RBAC).
 *
 * Displays a table of scope rules with add/edit/delete capabilities.
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminDataScopesApi } from "../../api/modules/admin";
import type { DataScopeRecord, DataScopeBody } from "../../api/modules/admin";

interface RoleDataScopeProps {
  open: boolean;
  roleName: string | null;
  onClose: () => void;
  /** 内嵌模式：作为角色工作台 Tab 渲染，不套外层 Modal。 */
  embedded?: boolean;
}

const SCOPE_TYPE_OPTIONS = [
  { value: "all", label: "全部数据" },
  { value: "dept_and_child", label: "本部门及子部门" },
  { value: "dept", label: "本部门" },
  { value: "self", label: "仅本人" },
  { value: "custom", label: "自定义" },
];

const SCOPE_TYPE_COLORS: Record<string, string> = {
  all: "green",
  dept_and_child: "blue",
  dept: "cyan",
  self: "orange",
  custom: "purple",
};

function RoleDataScope({ open, roleName, onClose, embedded }: RoleDataScopeProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [scopes, setScopes] = useState<DataScopeRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingScope, setEditingScope] = useState<DataScopeRecord | "new" | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    if (!roleName) return;
    setLoading(true);
    try {
      const data = await adminDataScopesApi.getRoleScopes(roleName);
      setScopes(data);
    } catch (err) {
      console.error("Failed to load data scopes:", err);
      message.error(t("admin.roles.scopeLoadFailed", "加载数据范围失败"));
    } finally {
      setLoading(false);
    }
  }, [roleName, message, t]);

  useEffect(() => {
    if ((embedded || open) && roleName) load();
  }, [embedded, open, roleName, load]);

  const openEditor = (scope: DataScopeRecord | "new") => {
    setEditingScope(scope);
    setEditOpen(true);
    if (scope === "new") {
      form.setFieldsValue({ resource: "", scope_type: "all", scope_value: "", description: "" });
    } else {
      form.setFieldsValue({
        resource: scope.resource,
        scope_type: scope.scope_type,
        scope_value: scope.scope_value,
        description: scope.description,
      });
    }
  };

  const handleSave = async () => {
    if (!roleName) return;
    const values = await form.validateFields();
    const body: DataScopeBody = {
      resource: values.resource,
      scope_type: values.scope_type,
      scope_value: values.scope_value || undefined,
      description: values.description || undefined,
    };
    try {
      await adminDataScopesApi.setRoleScope(roleName, body);
      message.success(t("admin.roles.scopeSaved", "数据范围已保存"));
      setEditOpen(false);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (resource: string) => {
    if (!roleName) return;
    try {
      await adminDataScopesApi.deleteRoleScope(roleName, resource);
      message.success(t("admin.roles.scopeDeleted", "数据范围已删除"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const scopeTypeValue = Form.useWatch("scope_type", form);

  const columns = [
    {
      title: t("admin.roles.scopeResource", "资源类型"),
      dataIndex: "resource",
      align: "center" as const,
    },
    {
      title: t("admin.roles.scopeType", "范围类型"),
      dataIndex: "scope_type",
      align: "center" as const,
      render: (v: string) => (
        <Tag color={SCOPE_TYPE_COLORS[v] ?? "default"}>
          {SCOPE_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v}
        </Tag>
      ),
    },
    {
      title: t("admin.roles.scopeValue", "范围值"),
      dataIndex: "scope_value",
      align: "center" as const,
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.roles.scopeDescription", "描述"),
      dataIndex: "description",
      align: "center" as const,
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.roles.actions", "操作"),
      key: "actions",
      align: "center" as const,
      width: 150,
      render: (_: unknown, record: DataScopeRecord) => (
        <Space size="small">
          <Button size="small" onClick={() => openEditor(record)}>
            {t("common.edit", "Edit")}
          </Button>
          <Popconfirm
            title={t("admin.roles.scopeDeleteConfirm", "确定删除此数据范围规则？")}
            onConfirm={() => handleDelete(record.resource)}
          >
            <Button size="small" danger>
              {t("common.delete", "Delete")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const inner = (
    <>
      <div style={{ marginBottom: 12 }}>
        <Button type="primary" size="small" onClick={() => openEditor("new")}>
          {t("admin.roles.addScope", "新增规则")}
        </Button>
      </div>
      <Table<DataScopeRecord>
        rowKey="id"
        loading={loading}
        dataSource={scopes}
        columns={columns}
        pagination={false}
        size="small"
        locale={{ emptyText: t("admin.roles.noScopes", "暂无数据范围规则") }}
      />
    </>
  );

  return (
    <>
      {embedded ? (
        inner
      ) : (
        <Modal
          title={`${t("admin.roles.dataScope", "数据范围")} — ${roleName ?? ""}`}
          open={open}
          onCancel={onClose}
          footer={null}
          width={700}
          destroyOnHidden
        >
          {inner}
        </Modal>
      )}

      {/* Nested edit modal */}
      <Modal
        title={
          editingScope === "new"
            ? t("admin.roles.addScope", "新增规则")
            : t("admin.roles.editScope", "编辑规则")
        }
        open={editOpen}
        onOk={handleSave}
        onCancel={() => setEditOpen(false)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="resource"
            label={t("admin.roles.scopeResource", "资源类型")}
            rules={[{ required: true }]}
          >
            <Input placeholder="agent / kb / model" disabled={editingScope !== "new"} />
          </Form.Item>
          <Form.Item
            name="scope_type"
            label={t("admin.roles.scopeType", "范围类型")}
            rules={[{ required: true }]}
          >
            <Select options={SCOPE_TYPE_OPTIONS} />
          </Form.Item>
          {scopeTypeValue === "custom" && (
            <Form.Item
              name="scope_value"
              label={t("admin.roles.scopeValue", "自定义范围值")}
              extra={t("admin.roles.scopeValueHint", "例如部门ID列表，用逗号分隔")}
            >
              <Input placeholder="dept_001,dept_002" />
            </Form.Item>
          )}
          <Form.Item name="description" label={t("admin.roles.scopeDescription", "描述")}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default RoleDataScope;
