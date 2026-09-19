/**
 * RolePermAssign — Modal for assigning permissions to a role (M7 PG-RBAC).
 *
 * Shows a checkable tree grouped by resource domain.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Modal, Spin, Tree, Empty } from "antd";
import type { DataNode } from "antd/es/tree";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminPermissionsApi } from "../../api/modules/admin";
import type { PermissionRecord } from "../../api/modules/admin";

interface RolePermAssignProps {
  open: boolean;
  roleName: string | null;
  onClose: () => void;
  /** 内嵌模式：作为角色工作台 Tab 渲染，不套外层 Modal。 */
  embedded?: boolean;
}

function RolePermAssign({ open, roleName, onClose, embedded }: RolePermAssignProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [allPerms, setAllPerms] = useState<PermissionRecord[]>([]);
  const [checkedIds, setCheckedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!roleName) return;
    setLoading(true);
    try {
      const [perms, rolePerms] = await Promise.all([
        adminPermissionsApi.list(),
        adminPermissionsApi.getRolePermissions(roleName),
      ]);
      setAllPerms(perms);
      setCheckedIds(rolePerms);
    } catch (err) {
      console.error("Failed to load permission assignment:", err);
      message.error(t("admin.roles.permLoadFailed", "加载权限列表失败"));
    } finally {
      setLoading(false);
    }
  }, [roleName, message, t]);

  useEffect(() => {
    if ((embedded || open) && roleName) load();
  }, [embedded, open, roleName, load]);

  // Build tree: resource → permissions
  const treeData: DataNode[] = useMemo(() => {
    const map = new Map<string, PermissionRecord[]>();
    for (const p of allPerms) {
      const key = p.resource || "other";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(p);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([resource, perms]) => ({
        key: `res:${resource}`,
        title: `${resource} (${perms.length})`,
        children: perms.map((p) => ({
          key: p.id,
          title: `${p.code} — ${p.name}`,
        })),
      }));
  }, [allPerms]);

  const handleOk = async () => {
    if (!roleName) return;
    setSaving(true);
    try {
      // Filter out group keys (res:xxx), only keep permission IDs
      const permIds = checkedIds.filter((id) => !id.startsWith("res:"));
      await adminPermissionsApi.setRolePermissions(roleName, permIds);
      message.success(t("admin.roles.permSaved", "权限分配已保存"));
      onClose();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  const inner = (
    <Spin spinning={loading}>
      {allPerms.length === 0 && !loading ? (
        <Empty description={t("admin.roles.noPerms", "暂无权限数据")} />
      ) : (
        <Tree
          checkable
          treeData={treeData}
          checkedKeys={checkedIds}
          onCheck={(checked) => {
            // checked can be Key[] or { checked: Key[]; halfChecked: Key[] }
            const keys = Array.isArray(checked) ? checked : checked.checked;
            setCheckedIds(keys.map(String));
          }}
          defaultExpandAll
          height={embedded ? 460 : 400}
        />
      )}
    </Spin>
  );

  return (
    <>
      {embedded ? (
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <span style={{ color: "var(--pg-ink-2, #4c5670)", fontSize: 13 }}>
              {t(
                "admin.roles.permHint",
                "设置角色对应的功能操作、后台管理权限",
              )}
            </span>
            <Button type="primary" loading={saving} onClick={handleOk}>
              {t("common.save", "保存")}
            </Button>
          </div>
          {inner}
        </div>
      ) : (
        <Modal
          title={`${t("admin.roles.assignPerms", "分配权限")} — ${roleName ?? ""}`}
          open={open}
          onOk={handleOk}
          onCancel={onClose}
          confirmLoading={saving}
          width={600}
          destroyOnHidden
        >
          {inner}
        </Modal>
      )}
    </>
  );
}

export default RolePermAssign;
