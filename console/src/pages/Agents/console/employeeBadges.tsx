/**
 * Agents/console/employeeBadges.tsx — 注册表徽标组（形态 / 可见性 / 状态）。
 *
 * 枚举文案全部走 i18n（后端只回 code），tone 复用全站 .pg-pill[data-tone]
 * 唯一色板，页面内不再自配颜色，暗色自动跟随 --pg-tone-* 翻转。
 */
import { useTranslation } from "react-i18next";
import type {
  DigitalEmployee,
  EmployeeKind,
  EmployeeVisibility,
} from "@/api/modules/employeeRegistry";

/** 形态 → pill tone（数字员工紫、专家团青绿、原生蓝、工作流灰）。 */
const KIND_TONE: Record<EmployeeKind, string> = {
  agent: "blue",
  expert: "violet",
  team: "teal",
  workflow: "gray",
};

/** 可见范围 → pill tone（部门专属需要被注意到，故用琥珀）。 */
const VISIBILITY_TONE: Record<EmployeeVisibility, string> = {
  org: "gray",
  department: "amber",
  private: "gray",
};

export function KindBadge({ kind }: { kind: EmployeeKind }) {
  const { t } = useTranslation();
  return (
    <span className="pg-pill" data-tone={KIND_TONE[kind] ?? "gray"}>
      {t(`employee.kind.${kind}`)}
    </span>
  );
}

/**
 * 可见范围徽标：部门专属额外带出归属部门名，让"这是谁的人"一眼可读。
 *
 * 未治理行不渲染：后端返回的 org 是默认语义而非人工决策，展示会误导
 * 「这台机器已经被治理过了」。
 */
export function VisibilityBadge({ employee }: { employee: DigitalEmployee }) {
  const { t } = useTranslation();
  if (!employee.governed) {
    return null;
  }
  const label = t(`employee.visibility.${employee.visibility}`);
  const scoped =
    employee.visibility === "department" && employee.department_name
      ? `${label} · ${employee.department_name}`
      : label;
  return (
    <span
      className="pg-pill"
      data-tone={VISIBILITY_TONE[employee.visibility] ?? "gray"}
      title={scoped}
    >
      {scoped}
    </span>
  );
}

/** 生命周期优先（草稿/归档语义更准确），否则回退运行状态。 */
export function StatusBadge({ employee }: { employee: DigitalEmployee }) {
  const { t } = useTranslation();
  if (employee.lifecycle_status === "draft") {
    return (
      <span className="pg-pill" data-tone="blue">
        {t("employee.lifecycle.draft")}
      </span>
    );
  }
  if (employee.lifecycle_status === "archived") {
    return (
      <span className="pg-pill" data-tone="gray">
        {t("employee.lifecycle.archived")}
      </span>
    );
  }
  const status = employee.startup_status || (employee.enabled ? "pending" : "disabled");
  const tone = status === "running" ? "green" : status === "failed" ? "red" : "gray";
  return (
    <span className="pg-pill" data-tone={tone}>
      {t(`agent.status.${status}`)}
    </span>
  );
}

/** 专家团编排模式徽标（router / pipeline，团卡专用）。 */
export function ModeBadge({ mode }: { mode: string }) {
  const { t } = useTranslation();
  if (!mode) {
    return null;
  }
  return (
    <span className="pg-pill" data-tone="teal">
      {t(`employee.teamMode.${mode}`)}
    </span>
  );
}
