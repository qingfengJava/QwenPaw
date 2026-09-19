/**
 * Admin/Permissions — Permission registry management (M7 PG-RBAC).
 *
 * Provides table view and grouped-by-resource view with CRUD operations.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { HasPerm } from "@/components/HasPerm";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminPermissionsApi } from "../../api/modules/admin";
import type { PermissionRecord, PermissionCreateBody, PermissionUpdateBody } from "../../api/modules/admin";
import styles from "./admin.module.less";

const { Search } = Input;

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const ACTION_OPTIONS = [
  "list", "create", "update", "delete", "manage",
  "read", "write", "use", "invoke",
].map((a) => ({ value: a, label: a }));

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function PermissionsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [permissions, setPermissions] = useState<PermissionRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"table" | "grouped">("table");
  const [filterResource, setFilterResource] = useState<string | undefined>(undefined);
  const [searchText, setSearchText] = useState("");
  const [editing, setEditing] = useState<PermissionRecord | "new" | null>(null);
  const [form] = Form.useForm();

  // ── Data loading ──────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await adminPermissionsApi.list();
      setPermissions(list);
    } catch (err) {
      console.error("Failed to load permissions:", err);
      message.error(t("admin.permissions.loadFailed", "Failed to load permissions"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  // ── Derived data ──────────────────────────────────────────────────────────

  const resources = useMemo(() => {
    const set = new Set(permissions.map((p) => p.resource).filter(Boolean));
    return Array.from(set).sort().map((r) => ({ value: r, label: r }));
  }, [permissions]);

  const filtered = useMemo(() => {
    let list = permissions;
    if (filterResource) {
      list = list.filter((p) => p.resource === filterResource);
    }
    if (searchText) {
      const q = searchText.toLowerCase();
      list = list.filter(
        (p) =>
          p.code.toLowerCase().includes(q) ||
          p.name.toLowerCase().includes(q),
      );
    }
    return list;
  }, [permissions, filterResource, searchText]);

  const grouped = useMemo(() => {
    const map = new Map<string, PermissionRecord[]>();
    for (const p of filtered) {
      const key = p.resource || "other";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(p);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const openEditor = (record: PermissionRecord | "new") => {
    setEditing(record);
    if (record === "new") {
      form.setFieldsValue({
        code: "",
        name: "",
        resource: "",
        action: "",
        description: "",
      });
    } else {
      form.setFieldsValue({
        code: record.code,
        name: record.name,
        resource: record.resource,
        action: record.action,
        description: record.description,
      });
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      if (editing === "new") {
        const body: PermissionCreateBody = {
          code: values.code,
          name: values.name,
          resource: values.resource || undefined,
          action: values.action || undefined,
          description: values.description || undefined,
        };
        await adminPermissionsApi.create(body);
        message.success(t("admin.permissions.created", "Permission created"));
      } else if (editing) {
        const body: PermissionUpdateBody = {
          code: values.code,
          name: values.name,
          resource: values.resource || undefined,
          action: values.action || undefined,
          description: values.description || undefined,
        };
        await adminPermissionsApi.update(editing.id, body);
        message.success(t("admin.permissions.saved", "Permission saved"));
      }
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (record: PermissionRecord) => {
    try {
      await adminPermissionsApi.delete(record.id);
      message.success(t("admin.permissions.deleted", "Permission deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  // ── Table columns ─────────────────────────────────────────────────────────

  const columns = [
    {
      title: t("admin.permissions.code", "权限码"),
      dataIndex: "code",
      align: "center" as const,
      render: (code: string) => <Tag color="geekblue">{code}</Tag>,
    },
    {
      title: t("admin.permissions.name", "显示名"),
      dataIndex: "name",
      align: "center" as const,
    },
    {
      title: t("admin.permissions.resource", "资源域"),
      dataIndex: "resource",
      align: "center" as const,
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.permissions.action", "操作"),
      dataIndex: "action",
      align: "center" as const,
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.permissions.description", "描述"),
      dataIndex: "description",
      align: "center" as const,
      render: (v: string) => v || "—",
      ellipsis: true,
    },
    {
      title: t("admin.permissions.actions", "操作列"),
      key: "actions",
      align: "center" as const,
      width: 150,
      render: (_: unknown, record: PermissionRecord) => (
        <HasPerm code="admin:permissions">
          <Space size="small">
            <Button size="small" onClick={() => openEditor(record)}>
              {t("common.edit", "Edit")}
            </Button>
            <Popconfirm
              title={t("admin.permissions.deleteConfirm", "确定删除此权限？")}
              onConfirm={() => handleDelete(record)}
            >
              <Button size="small" danger>
                {t("common.delete", "Delete")}
              </Button>
            </Popconfirm>
          </Space>
        </HasPerm>
      ),
    },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminPermissions", "Permissions")}
        extra={
          <HasPerm code="admin:permissions">
            <Button type="primary" onClick={() => openEditor("new")}>
              {t("admin.permissions.create", "新增权限")}
            </Button>
          </HasPerm>
        }
      />

      {/* Toolbar */}
      <div className={styles.toolbar}>
        <Select
          style={{ width: 160 }}
          placeholder={t("admin.permissions.filterResource", "按资源域筛选")}
          allowClear
          options={resources}
          value={filterResource}
          onChange={setFilterResource}
        />
        <Search
          style={{ width: 240 }}
          placeholder={t("admin.permissions.search", "搜索权限码或名称")}
          allowClear
          onSearch={setSearchText}
          onChange={(e) => !e.target.value && setSearchText("")}
        />
        <div style={{ marginLeft: "auto" }}>
          <Radio.Group
            value={viewMode}
            onChange={(e) => setViewMode(e.target.value)}
            optionType="button"
            buttonStyle="solid"
            size="small"
          >
            <Radio.Button value="table">
              {t("admin.permissions.tableView", "表格视图")}
            </Radio.Button>
            <Radio.Button value="grouped">
              {t("admin.permissions.groupView", "分组视图")}
            </Radio.Button>
          </Radio.Group>
        </div>
      </div>

      {/* Content */}
      {viewMode === "table" ? (
        <Table<PermissionRecord>
          rowKey="id"
          loading={loading}
          dataSource={filtered}
          columns={columns}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          size="middle"
        />
      ) : (
        <Collapse
          accordion
          items={grouped.map(([resource, perms]) => ({
            key: resource,
            label: (
              <span>
                <Tag color="blue">{resource}</Tag>
                <span style={{ color: "#888" }}>({perms.length})</span>
              </span>
            ),
            children: (
              <Table<PermissionRecord>
                rowKey="id"
                dataSource={perms}
                columns={columns}
                pagination={false}
                size="small"
              />
            ),
          }))}
        />
      )}

      {/* Create / Edit Modal */}
      <Modal
        title={
          editing === "new"
            ? t("admin.permissions.create", "新增权限")
            : t("admin.permissions.edit", "编辑权限")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
        width={520}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label={t("admin.permissions.code", "权限码")}
            rules={[
              { required: true, message: "请输入权限码" },
              { pattern: /^[\w]+:[\w]+$/, message: "格式: resource:action" },
            ]}
          >
            <Input placeholder="admin:users" disabled={editing !== "new"} />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("admin.permissions.name", "显示名")}
            rules={[{ required: true }]}
          >
            <Input placeholder="用户管理" />
          </Form.Item>
          <Form.Item name="resource" label={t("admin.permissions.resource", "资源域")}>
            <Select
              showSearch
              allowClear
              mode="tags"
              maxCount={1}
              placeholder={t("admin.permissions.resourcePlaceholder", "输入或选择资源域")}
              options={resources}
            />
          </Form.Item>
          <Form.Item name="action" label={t("admin.permissions.action", "操作")}>
            <Select
              showSearch
              allowClear
              placeholder={t("admin.permissions.actionPlaceholder", "选择或输入操作")}
              options={ACTION_OPTIONS}
            />
          </Form.Item>
          <Form.Item name="description" label={t("admin.permissions.description", "描述")}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default PermissionsPage;
