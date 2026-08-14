/**
 * Admin/Organization — org & department tree with member assignment
 * (XianWork Phase 1). Left: department tree; right: members of the
 * selected department. Department mirrors onto RBAC teams server-side.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  Tree,
} from "antd";
import type { DataNode } from "antd/es/tree";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminOrgsApi, adminUsersApi } from "../../api/modules/admin";
import type {
  AdminUserView,
  DepartmentTree,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

function toTreeNodes(nodes: DepartmentTree[]): DataNode[] {
  return nodes.map((node) => ({
    key: node.id,
    title: node.name,
    children: node.children.length ? toTreeNodes(node.children) : undefined,
  }));
}

function OrganizationPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [tree, setTree] = useState<DepartmentTree[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [members, setMembers] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [treeData, userList] = await Promise.all([
        adminOrgsApi.departmentTree(),
        adminUsersApi.list().catch(() => [] as AdminUserView[]),
      ]);
      setTree(treeData);
      setUsers(userList);
    } catch (err) {
      message.error(
        t("admin.org.loadFailed", "Failed to load organization"),
      );
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setMembers([]);
      return;
    }
    adminOrgsApi
      .departmentMembers(selected)
      .then((res) => setMembers(res.members))
      .catch(() => setMembers([]));
  }, [selected]);

  const selectedNode = useMemo(() => {
    const walk = (nodes: DepartmentTree[]): DepartmentTree | null => {
      for (const node of nodes) {
        if (node.id === selected) return node;
        const hit = walk(node.children);
        if (hit) return hit;
      }
      return null;
    };
    return selected ? walk(tree) : null;
  }, [selected, tree]);

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      await adminOrgsApi.createDepartment({
        name: values.name,
        parent_id: selected || null,
        description: values.description ?? "",
      });
      message.success(t("admin.org.created", "Department created"));
      setCreating(false);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    try {
      await adminOrgsApi.deleteDepartment(selected);
      message.success(t("admin.org.deleted", "Department deleted"));
      setSelected(null);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleAssign = async (username: string) => {
    if (!selected) return;
    try {
      await adminOrgsApi.assignMember(selected, username);
      const res = await adminOrgsApi.departmentMembers(selected);
      setMembers(res.members);
      message.success(t("admin.org.memberAdded", "Member assigned"));
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleRemoveMember = async (username: string) => {
    if (!selected) return;
    try {
      await adminOrgsApi.removeMember(selected, username);
      setMembers((prev) => prev.filter((m) => m !== username));
    } catch (err) {
      message.error(String(err));
    }
  };

  const candidateUsers = users.filter((u) => !members.includes(u.username));

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminOrg", "Organization")}
        extra={
          <Button type="primary" onClick={() => setCreating(true)}>
            {t("admin.org.create", "New department")}
          </Button>
        }
      />
      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ width: 320, flexShrink: 0 }}>
          <div
            style={{
              border: "1px solid var(--border-color, #e5e7eb)",
              borderRadius: 8,
              padding: 12,
            }}
          >
            <Tree
              treeData={toTreeNodes(tree)}
              selectedKeys={selected ? [selected] : []}
              onSelect={(keys) =>
                setSelected(keys.length ? String(keys[0]) : null)
              }
            />
          </div>
          {selectedNode && (
            <Popconfirm
              title={t(
                "admin.org.deleteConfirm",
                "Delete this department? (must be empty)",
              )}
              onConfirm={handleDelete}
            >
              <Button danger size="small" block style={{ marginTop: 12 }}>
                {t("admin.org.delete", "Delete department")}
              </Button>
            </Popconfirm>
          )}
        </div>
        <div style={{ flexGrow: 1 }}>
          <Table<string>
            rowKey={(m) => m}
            loading={loading}
            dataSource={members}
            pagination={false}
            locale={{ emptyText: t("admin.org.noMembers", "No members") }}
            columns={[
              {
                title: t("admin.org.member", "Member"),
                render: (m: string) => <Tag>{m}</Tag>,
              },
              {
                title: t("admin.org.actions", "Actions"),
                key: "actions",
                width: 120,
                render: (m: string) => (
                  <Button
                    size="small"
                    danger
                    onClick={() => handleRemoveMember(m)}
                  >
                    {t("common.remove", "Remove")}
                  </Button>
                ),
              },
            ]}
            title={() =>
              selectedNode
                ? `${t("admin.org.membersOf", "Members of")} ${selectedNode.name}`
                : t("admin.org.selectDept", "Select a department")
            }
            footer={() => (
              <Select
                style={{ width: 260 }}
                placeholder={t(
                  "admin.org.assignMember",
                  "Assign member to department",
                )}
                value={null}
                options={candidateUsers.map((u) => ({
                  value: u.username,
                  label: u.display_name
                    ? `${u.display_name} (${u.username})`
                    : u.username,
                }))}
                onChange={(v) => v && handleAssign(String(v))}
              />
            )}
          />
        </div>
      </div>

      <Modal
        title={t("admin.org.create", "New department")}
        open={creating}
        onOk={handleCreate}
        onCancel={() => setCreating(false)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.org.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.org.description", "Description")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default OrganizationPage;
