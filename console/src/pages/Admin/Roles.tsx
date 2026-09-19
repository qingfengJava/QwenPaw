/**
 * Admin/Roles — 角色管理工作台（企业级 RBAC 升级）。
 *
 * 左栏角色列表（添加/选择），右栏三 Tab：角色-功能权限 / 角色-数据范围 /
 * 角色-员工列表。内置角色不可删除；"分配菜单"作为辅助操作保留弹窗入口。
 * 视觉遵循 --pg-* token（见 admin.module.less）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Tabs,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { HasPerm } from "@/components/HasPerm";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminRolesApi } from "../../api/modules/admin";
import type { RoleRecord } from "../../api/modules/admin";
import RolePermAssign from "./RolePermAssign";
import RoleMenuAssign from "./RoleMenuAssign";
import RoleDataScope from "./RoleDataScope";
import RoleMembers from "./RoleMembers";
import styles from "./admin.module.less";

const DATA_SCOPE_OPTIONS = [
  { value: "all", labelKey: "admin.roles.scopeAll", fallback: "全部数据" },
  { value: "dept_and_child", labelKey: "admin.roles.scopeDeptChild", fallback: "本部门及子部门" },
  { value: "dept", labelKey: "admin.roles.scopeDept", fallback: "本部门" },
  { value: "self", labelKey: "admin.roles.scopeSelf", fallback: "仅本人" },
];

function RolesPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<RoleRecord | "new" | null>(null);
  const [menuAssignRole, setMenuAssignRole] = useState<string | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const roleList = await adminRolesApi.list();
      setRoles(roleList);
      setSelected((prev) => {
        if (prev && roleList.some((r) => r.name === prev)) return prev;
        return roleList.length ? roleList[0].name : null;
      });
    } catch (err) {
      console.error("Failed to load roles:", err);
      message.error(t("admin.roles.loadFailed", "加载角色失败"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const selectedRole = roles.find((r) => r.name === selected) || null;

  const openEditor = (role: RoleRecord | "new") => {
    setEditing(role);
    if (role === "new") {
      form.resetFields();
    } else {
      form.setFieldsValue({
        name: role.name,
        display_name: role.display_name || "",
        description: role.description || "",
        data_scope: role.data_scope || "self",
      });
    }
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    try {
      await adminRolesApi.upsert(values.name, {
        permissions: selectedRole?.permissions ?? [],
        description: values.description ?? "",
        display_name: values.display_name ?? "",
      });
      message.success(t("admin.roles.saved", "角色已保存"));
      setEditing(null);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (role: RoleRecord) => {
    try {
      await adminRolesApi.remove(role.name);
      message.success(t("admin.roles.deleted", "角色已删除"));
      if (selected === role.name) setSelected(null);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const scopeLabel = (v?: string) => {
    const opt = DATA_SCOPE_OPTIONS.find((o) => o.value === v);
    return opt ? t(opt.labelKey, opt.fallback) : v || "—";
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "管理")}
        current={t("nav.adminRoles", "角色管理")}
      />
      <div className={styles.workspaceLayout}>
        {/* 左栏：角色列表 */}
        <div className={styles.sidePanel}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span style={{ fontWeight: 600, color: "var(--pg-ink, #101623)" }}>
              {t("admin.roles.roleList", "角色")}
            </span>
            <HasPerm code="admin:rolesCreate">
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => openEditor("new")}>
                {t("common.add", "添加")}
              </Button>
            </HasPerm>
          </div>
          <div className={styles.sidePanelBody}>
            <div className={styles.roleList}>
              {roles.map((role) => (
                <div
                  key={role.name}
                  className={`${styles.roleListItem} ${
                    selected === role.name ? styles.roleListItemActive : ""
                  }`}
                  onClick={() => setSelected(role.name)}
                >
                  <div className={styles.roleItemName}>
                    {role.display_name || role.name}
                    {role.builtin ? (
                      <span className={styles.toneBlue}>
                        {t("admin.roles.builtin", "内置")}
                      </span>
                    ) : null}
                  </div>
                  <div className={styles.roleItemMeta}>
                    {t("admin.roles.permCount", "权限")} {role.permissions.length}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className={styles.sidePanelFooter}>
            {t("admin.roles.totalRoles", "共")} {roles.length}{" "}
            {t("admin.roles.totalRolesSuffix", "个角色")}
          </div>
        </div>

        {/* 右栏：三 Tab 详情 */}
        <div className={styles.mainPanel}>
          {selectedRole ? (
            <>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <h3 className={styles.mainTitle} style={{ margin: 0 }}>
                  {selectedRole.display_name || selectedRole.name}
                  <span
                    style={{
                      fontSize: 13,
                      color: "var(--pg-ink-3, #828ca6)",
                      marginLeft: 12,
                    }}
                  >
                    {selectedRole.name}
                  </span>
                  <span
                    className={styles.toneBlue}
                    style={{ marginLeft: 12 }}
                  >
                    {scopeLabel(selectedRole.data_scope)}
                  </span>
                </h3>
                <div style={{ display: "flex", gap: 8 }}>
                  <HasPerm code="admin:rolesAssign">
                    <Button size="small" onClick={() => setMenuAssignRole(selectedRole.name)}>
                      {t("admin.roles.assignMenus", "分配菜单")}
                    </Button>
                  </HasPerm>
                  {!selectedRole.builtin && (
                    <HasPerm code="admin:rolesUpdate">
                      <Button size="small" onClick={() => openEditor(selectedRole)}>
                        {t("common.edit", "编辑")}
                      </Button>
                    </HasPerm>
                  )}
                  {!selectedRole.builtin && (
                    <HasPerm code="admin:rolesDelete">
                      <Popconfirm
                        title={t("admin.roles.deleteConfirm", "删除该角色？")}
                        onConfirm={() => handleDelete(selectedRole)}
                      >
                        <Button size="small" danger>
                          {t("common.delete", "删除")}
                        </Button>
                      </Popconfirm>
                    </HasPerm>
                  )}
                </div>
              </div>

              <Tabs
                key={selectedRole.name}
                className={styles.fadeIn}
                defaultActiveKey="perms"
                items={[
                  {
                    key: "perms",
                    label: t("admin.roles.tabPerms", "角色-功能权限"),
                    children: (
                      <RolePermAssign
                        embedded
                        open={false}
                        roleName={selectedRole.name}
                        onClose={() => undefined}
                      />
                    ),
                  },
                  {
                    key: "scopes",
                    label: t("admin.roles.tabScopes", "角色-数据范围"),
                    children: (
                      <RoleDataScope
                        embedded
                        open={false}
                        roleName={selectedRole.name}
                        onClose={() => undefined}
                      />
                    ),
                  },
                  {
                    key: "members",
                    label: t("admin.roles.tabMembers", "角色-员工列表"),
                    children: <RoleMembers roleName={selectedRole.name} />,
                  },
                ]}
              />
            </>
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "var(--pg-ink-3, #828ca6)" }}>
              {loading ? t("common.loading", "加载中…") : t("admin.roles.pickRole", "请选择角色")}
            </div>
          )}
        </div>
      </div>

      {/* 角色新建/编辑弹窗 */}
      <Modal
        title={
          editing === "new"
            ? t("admin.roles.create", "新建角色")
            : t("admin.roles.edit", "编辑角色")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.roles.name", "角色标识")}
            rules={[{ required: true }]}
          >
            <Input disabled={editing !== "new"} placeholder="support_lead" />
          </Form.Item>
          <Form.Item name="display_name" label={t("admin.roles.displayName", "显示名")}>
            <Input placeholder="客服主管" />
          </Form.Item>
          <Form.Item name="data_scope" label={t("admin.roles.dataScope", "数据范围")} initialValue="self">
            <Select options={DATA_SCOPE_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey, o.fallback) }))} />
          </Form.Item>
          <Form.Item name="description" label={t("admin.roles.description", "描述")}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 分配菜单弹窗（保留既有能力） */}
      <RoleMenuAssign
        open={menuAssignRole !== null}
        roleName={menuAssignRole}
        onClose={() => {
          setMenuAssignRole(null);
          load();
        }}
      />
    </div>
  );
}

export default RolesPage;
