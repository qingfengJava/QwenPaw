/**
 * Agents/console/EmployeeKindCard.tsx — 单体员工卡（原生智能体 / 数字员工）。
 *
 * 结构：形象 + 名称与归属副标 → 状态胶囊与操作 → 描述两行 →
 * 部门/可见性徽标 → 脚注（模型 / 后端 / 进入箭头）。
 *
 * 头像口径交给 EmployeeKindAvatar，与工作台共用同一渲染实现。
 */
import { useTranslation } from "react-i18next";
import { ArrowRight, Cpu, Pin } from "lucide-react";
import EmployeeKindAvatar from "@/components/EmployeeKindAvatar";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import { StatusBadge, VisibilityBadge } from "./employeeBadges";
import styles from "./console.module.less";

export interface EmployeeKindCardProps {
  employee: DigitalEmployee;
  /** 卡片主体点击：新标签页打开工作台（与表格/箭头行为统一）。 */
  onOpen: (employee: DigitalEmployee) => void;
  /** 右上角操作区（治理入口 + 更多菜单），由页面注入以保持卡片无状态。 */
  actions?: React.ReactNode;
}

export function EmployeeKindCard({
  employee,
  onOpen,
  actions,
}: EmployeeKindCardProps) {
  const { t } = useTranslation();
  const backendLabel =
    employee.backend === "qwenpaw"
      ? t("agent.backend.nativeBadge")
      : employee.backend;

  return (
    <div
      className={styles.card}
      role="button"
      tabIndex={0}
      aria-label={employee.name}
      data-employee-agent={employee.agent_id}
      onClick={() => onOpen(employee)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(employee);
        }
      }}
    >
      <span className={styles.cardAccent} aria-hidden="true" />

      <div className={styles.cardHead}>
        <EmployeeKindAvatar employee={employee} size={44} />

        <div className={styles.cardTitleWrap}>
          <div className={styles.nameRow}>
            <span className={styles.name} title={employee.name}>
              {employee.name}
            </span>
            {employee.pinned ? <Pin size={13} className={styles.pinIcon} /> : null}
          </div>
          <div className={styles.sub} title={employee.title || employee.entity_id}>
            {employee.title || employee.entity_id}
          </div>
        </div>

        <div className={styles.cardActions} onClick={(event) => event.stopPropagation()}>
          {actions}
        </div>
      </div>

      <p
        className={`${styles.desc} ${
          employee.description ? "" : styles.descEmpty
        }`}
      >
        {employee.description || t("workbench.noDescription")}
      </p>

      <div className={styles.badges}>
        <StatusBadge employee={employee} />
        <VisibilityBadge employee={employee} />
      </div>

      <div className={styles.foot}>
        {employee.model_label ? (
          <span className={styles.chip} title={employee.model_label}>
            <Cpu size={11} />
            {employee.model_label}
          </span>
        ) : null}
        {backendLabel ? <span className={styles.chip}>{backendLabel}</span> : null}
        <ArrowRight size={15} className={styles.footArrow} aria-hidden="true" />
      </div>
    </div>
  );
}
