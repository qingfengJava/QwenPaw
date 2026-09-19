/**
 * RoleMenuAssign — Modal for assigning menus to a role (M7 PG-RBAC).
 *
 * Shows a checkable menu tree; loads current role's menu assignments.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Modal, Spin, Tree, Empty } from "antd";
import type { DataNode } from "antd/es/tree";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminMenusApi } from "../../api/modules/admin";
import type { MenuItem } from "../../stores/permissionStore";

interface RoleMenuAssignProps {
  open: boolean;
  roleName: string | null;
  onClose: () => void;
}

function toCheckableTree(items: MenuItem[]): DataNode[] {
  return items.map((item) => ({
    key: item.id,
    title: `${item.name} (${item.menu_type})`,
    children: item.children?.length ? toCheckableTree(item.children) : undefined,
  }));
}

function RoleMenuAssign({ open, roleName, onClose }: RoleMenuAssignProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [menuTree, setMenuTree] = useState<MenuItem[]>([]);
  const [checkedIds, setCheckedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!roleName) return;
    setLoading(true);
    try {
      const [tree, roleMenus] = await Promise.all([
        adminMenusApi.getTree(),
        adminMenusApi.getRoleMenus(roleName),
      ]);
      setMenuTree(tree);
      setCheckedIds(roleMenus);
    } catch (err) {
      console.error("Failed to load menu assignment:", err);
      message.error(t("admin.roles.menuLoadFailed", "加载菜单列表失败"));
    } finally {
      setLoading(false);
    }
  }, [roleName, message, t]);

  useEffect(() => {
    if (open && roleName) load();
  }, [open, roleName, load]);

  const treeData = useMemo(() => toCheckableTree(menuTree), [menuTree]);

  const handleOk = async () => {
    if (!roleName) return;
    setSaving(true);
    try {
      await adminMenusApi.setRoleMenus(roleName, checkedIds);
      message.success(t("admin.roles.menuSaved", "菜单分配已保存"));
      onClose();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`${t("admin.roles.assignMenus", "分配菜单")} — ${roleName ?? ""}`}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      confirmLoading={saving}
      width={600}
      destroyOnHidden
    >
      <Spin spinning={loading}>
        {menuTree.length === 0 && !loading ? (
          <Empty description={t("admin.roles.noMenus", "暂无菜单数据")} />
        ) : (
          <Tree
            checkable
            treeData={treeData}
            checkedKeys={checkedIds}
            onCheck={(checked) => {
              const keys = Array.isArray(checked) ? checked : checked.checked;
              setCheckedIds(keys.map(String));
            }}
            defaultExpandAll
            height={400}
          />
        )}
      </Spin>
    </Modal>
  );
}

export default RoleMenuAssign;
