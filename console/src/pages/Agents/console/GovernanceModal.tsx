/**
 * Agents/console/GovernanceModal.tsx — 归属与可见性治理弹窗（单个 / 批量共用）。
 *
 * 三个可治理维度：归属部门（唯一）、可见范围（三态）、授权部门（部门专属时的
 * 多方共享）。弹窗内直接说明"改完谁会受影响"，避免管理员盲改权限。
 */
import { useEffect, useMemo, useState } from "react";
import { Alert, Modal, Radio, Select, TreeSelect } from "antd";
import { useTranslation } from "react-i18next";
import type { DepartmentTree } from "@/api/modules/admin";
import type {
  DigitalEmployee,
  EmployeeVisibility,
  GovernancePayload,
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
  const [saving, setSaving] = useState(false);

  const batch = targets.length > 1;

  // 打开时回填首个目标的治理态；批量场景只预填公共值，避免"看起来已统一"的错觉
  useEffect(() => {
    if (!open) {
      return;
    }
    const first = targets[0];
    setDepartmentId(first?.department_id ?? undefined);
    setVisibility(first?.visibility ?? "org");
    setGranted(first?.granted_departments ?? []);
    setSaving(false);
  }, [open, targets]);

  const treeData = useMemo(() => toTreeData(departments), [departments]);
  const departmentOptions = useMemo(() => flatten(departments), [departments]);

  const handleOk = async () => {
    setSaving(true);
    try {
      await onSubmit({
        department_id: departmentId ?? "",
        visibility,
        granted_departments: visibility === "department" ? granted : [],
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
