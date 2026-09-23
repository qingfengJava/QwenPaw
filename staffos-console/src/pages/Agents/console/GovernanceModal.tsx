/**
 * Agents/console/GovernanceModal.tsx — 归属与可见性治理弹窗（单个 / 批量共用）。
 *
 * 三个可治理维度：归属部门（唯一）、可见范围（三态）、授权部门（部门专属时的
 * 多方共享）。弹窗内直接说明"改完谁会受影响"，避免管理员盲改权限。
 */
import { useEffect, useMemo, useState } from "react";
import { Alert, Divider, Modal, Radio, Select, TreeSelect } from "antd";
import { useTranslation } from "react-i18next";
import type { DepartmentTree } from "@/api/modules/admin";
import { adminUsersApi } from "@/api/modules/admin/users";
import type { AdminUserView } from "@/api/modules/admin/types";
import type {
  DigitalEmployee,
  EmployeeVisibility,
  GovernancePayload,
  ManageVisibility,
} from "@/api/modules/employeeRegistry";
import styles from "./console.module.less";

interface GovernanceModalProps {
  open: boolean;
  /** 治理目标：1 个即单员工编辑，多个即批量套用。 */
  targets: DigitalEmployee[];
  departments: DepartmentTree[];
  onCancel: () => void;
  onSubmit: (payload: GovernancePayload) => Promise<void>;
}

/** TreeSelect 节点形状（部门树只读展示，不需要 disabled 等扩展位）。 */
interface DeptTreeNode {
  value: string;
  title: string;
  children?: DeptTreeNode[];
}

/** 部门树 → TreeSelect 数据（value 用部门 id，title 用部门名）。 */
function toTreeData(nodes: DepartmentTree[]): DeptTreeNode[] {
  return nodes.map((node) => ({
    value: node.id,
    title: node.name,
    children: node.children.length ? toTreeData(node.children) : undefined,
  }));
}

/** 部门树拍平为 Select 选项（授权部门是多选，无需层级缩进）。 */
function flatten(nodes: DepartmentTree[]): { value: string; label: string }[] {
  return nodes.flatMap((node) => [
    { value: node.id, label: node.name },
    ...flatten(node.children),
  ]);
}

export function GovernanceModal({
  open,
  targets,
  departments,
  onCancel,
  onSubmit,
}: GovernanceModalProps) {
  const { t } = useTranslation();
  const [departmentId, setDepartmentId] = useState<string | undefined>();
  const [visibility, setVisibility] = useState<EmployeeVisibility>("org");
  const [granted, setGranted] = useState<string[]>([]);
  // 后台配置域（可配置范围）：与使用维对称的三控件状态。
  // manage_visibility 仅 private/department；manage_granted_users 为跨部门兜底。
  const [manageVisibility, setManageVisibility] =
    useState<ManageVisibility>("private");
  const [manageGranted, setManageGranted] = useState<string[]>([]);
  const [manageUsers, setManageUsers] = useState<string[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [saving, setSaving] = useState(false);

  const batch = targets.length > 1;

  // 预填规则：单条回填该员工的治理态；批量仅预填「全目标一致」的维度，
  // 不一致的维度留空/回落默认，避免把首条值静默覆盖到所有选中者
  useEffect(() => {
    if (!open) {
      return;
    }
    const first = targets[0];
    const uniform = <T,>(values: T[]): boolean =>
      targets.length === 1 || values.every((value) => value === values[0]);
    const departmentIds = targets.map((row) => row.department_id ?? "");
    const visibilities = targets.map((row) => row.visibility);
    const grantedLists = targets.map((row) =>
      JSON.stringify(row.granted_departments ?? []),
    );
    setDepartmentId(
      uniform(departmentIds) ? (first?.department_id ?? undefined) : undefined,
    );
    setVisibility(uniform(visibilities) ? (first?.visibility ?? "org") : "org");
    setGranted(
      uniform(grantedLists) ? (first?.granted_departments ?? []) : [],
    );
    // 可配置范围（管理授权维）同样按「全目标一致才预填」规则回填
    const manageVisibilities = targets.map((row) => row.manage_visibility);
    const manageGrantedLists = targets.map((row) =>
      JSON.stringify(row.manage_granted_departments ?? []),
    );
    const manageUserLists = targets.map((row) =>
      JSON.stringify(row.manage_granted_users ?? []),
    );
    setManageVisibility(
      uniform(manageVisibilities)
        ? (first?.manage_visibility ?? "private")
        : "private",
    );
    setManageGranted(
      uniform(manageGrantedLists)
        ? (first?.manage_granted_departments ?? [])
        : [],
    );
    setManageUsers(
      uniform(manageUserLists) ? (first?.manage_granted_users ?? []) : [],
    );
    setSaving(false);
  }, [open, targets]);

  // 管理授权用户候选：弹窗打开时拉取一次账号列表（治理面为 admin 专属，
  // 有权访问 /admin/users）。失败静默降级为空候选，不阻断部门维度治理。
  useEffect(() => {
    if (!open) {
      return;
    }
    let alive = true;
    adminUsersApi
      .list()
      .then((list) => {
        if (alive) setUsers(list);
      })
      .catch(() => {
        if (alive) setUsers([]);
      });
    return () => {
      alive = false;
    };
  }, [open]);

  const treeData = useMemo(() => toTreeData(departments), [departments]);
  const departmentOptions = useMemo(() => flatten(departments), [departments]);
  // 管理授权用户候选项：value 用 username（后端授权以用户名为准），
  // label 展示 display_name + username 便于管理员辨识同名账号。
  const userOptions = useMemo(
    () =>
      users.map((user) => ({
        value: user.username,
        label: user.display_name
          ? `${user.display_name} (${user.username})`
          : user.username,
      })),
    [users],
  );

  const handleOk = async () => {
    setSaving(true);
    try {
      await onSubmit({
        department_id: departmentId ?? "",
        visibility,
        granted_departments: visibility === "department" ? granted : [],
        // 后台配置域：manage_visibility 恒提交；授权部门仅 department 范围生效，
        // 否则清空；授权用户为跨部门兜底，独立于 manage_visibility 恒提交。
        manage_visibility: manageVisibility,
        manage_granted_departments:
          manageVisibility === "department" ? manageGranted : [],
        manage_granted_users: manageUsers,
      });
    } finally {
      setSaving(false);
    }
  };

  const departmentMissing = visibility === "department" && !departmentId && !granted.length;

  return (
    <Modal
      open={open}
      destroyOnHidden
      confirmLoading={saving}
      title={t("employee.governance.title")}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
      okButtonProps={{ disabled: departmentMissing }}
      onOk={() => {
        void handleOk();
      }}
      onCancel={onCancel}
      width={560}
    >
      {batch ? (
        <div className={styles.targetList}>
          {targets.map((target) => (
            <span key={target.agent_id} className={`pg-pill ${styles.targetChip}`}>
              {target.name}
            </span>
          ))}
        </div>
      ) : null}

      <div className={styles.modalBody}>
        <div>
          <div className={styles.fieldLabel}>
            {t("employee.governance.department")}
          </div>
          <TreeSelect
            style={{ width: "100%" }}
            treeData={treeData}
            value={departmentId}
            allowClear
            treeDefaultExpandAll
            placeholder={t("employee.governance.departmentPlaceholder")}
            onChange={(value) => setDepartmentId(value ?? undefined)}
          />
          <div className={styles.fieldHint}>
            {t("employee.governance.departmentHint")}
          </div>
        </div>

        <div>
          <div className={styles.fieldLabel}>
            {t("employee.governance.visibility")}
          </div>
          <Radio.Group
            value={visibility}
            onChange={(event) => setVisibility(event.target.value as EmployeeVisibility)}
            options={[
              { value: "org", label: t("employee.visibility.org") },
              { value: "department", label: t("employee.visibility.department") },
              { value: "private", label: t("employee.visibility.private") },
            ]}
            optionType="button"
            buttonStyle="solid"
          />
          <div className={styles.fieldHint}>
            {t(`employee.governance.visibilityHint.${visibility}`)}
          </div>
        </div>

        {visibility === "department" ? (
          <div>
            <div className={styles.fieldLabel}>
              {t("employee.governance.granted")}
            </div>
            <Select
              mode="multiple"
              style={{ width: "100%" }}
              value={granted}
              options={departmentOptions}
              allowClear
              maxTagCount="responsive"
              placeholder={t("employee.governance.grantedPlaceholder")}
              onChange={(value) => setGranted(value)}
            />
            <div className={styles.fieldHint}>
              {t("employee.governance.grantedHint")}
            </div>
          </div>
        ) : null}

        <Divider style={{ margin: "8px 0" }}>
          {t(
            "employee.governance.manageSection",
            "可配置范围（后台管理授权）",
          )}
        </Divider>

        <div>
          <div className={styles.fieldLabel}>
            {t("employee.governance.manageVisibility", "可配置范围")}
          </div>
          <Radio.Group
            value={manageVisibility}
            onChange={(event) =>
              setManageVisibility(event.target.value as ManageVisibility)
            }
            options={[
              {
                value: "private",
                label: t("employee.manageVisibility.private", "仅创建者"),
              },
              {
                value: "department",
                label: t("employee.manageVisibility.department", "部门可配"),
              },
            ]}
            optionType="button"
            buttonStyle="solid"
          />
          <div className={styles.fieldHint}>
            {manageVisibility === "department"
              ? t(
                  "employee.governance.manageVisibilityHint.department",
                  "归属部门与管理授权部门（含下属）成员可重新配置该员工。",
                )
              : t(
                  "employee.governance.manageVisibilityHint.private",
                  "仅创建者、team_lead 与管理员可重新配置该员工（出厂最严）。",
                )}
          </div>
        </div>

        {manageVisibility === "department" ? (
          <div>
            <div className={styles.fieldLabel}>
              {t("employee.governance.manageGranted", "管理授权部门")}
            </div>
            <Select
              mode="multiple"
              style={{ width: "100%" }}
              value={manageGranted}
              options={departmentOptions}
              allowClear
              maxTagCount="responsive"
              placeholder={t(
                "employee.governance.manageGrantedPlaceholder",
                "选择可配置该员工的部门",
              )}
              onChange={(value) => setManageGranted(value)}
            />
            <div className={styles.fieldHint}>
              {t(
                "employee.governance.manageGrantedHint",
                "可配置集合 = 归属部门 ∪ 管理授权部门，授权自动覆盖其下属部门。",
              )}
            </div>
          </div>
        ) : null}

        <div>
          <div className={styles.fieldLabel}>
            {t("employee.governance.manageUsers", "管理授权用户")}
          </div>
          <Select
            mode="multiple"
            style={{ width: "100%" }}
            value={manageUsers}
            options={userOptions}
            allowClear
            showSearch
            optionFilterProp="label"
            maxTagCount="responsive"
            placeholder={t(
              "employee.governance.manageUsersPlaceholder",
              "按用户名跨部门显式授权可配置该员工",
            )}
            onChange={(value) => setManageUsers(value)}
          />
          <div className={styles.fieldHint}>
            {t(
              "employee.governance.manageUsersHint",
              "跨部门兜底：无论可配置范围如何，被授权用户都能配置该员工。",
            )}
          </div>
        </div>

        {departmentMissing ? (
          <Alert
            type="warning"
            showIcon
            message={t("employee.governance.needDepartment")}
          />
        ) : null}

        <div className={styles.impactNote}>
          {t("employee.governance.impact")}
        </div>
      </div>
    </Modal>
  );
}

/** 治理弹窗的保存按钮 loading 由组件内部托管，页面只需 await 提交结果。 */
export type { GovernanceModalProps };
