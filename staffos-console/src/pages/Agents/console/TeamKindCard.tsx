/**
 * Agents/console/TeamKindCard.tsx — 专家团卡（多员工协同编排）。
 *
 * 与单体员工卡的差异：头像位换成「成员形象堆叠」（最多 4 个 + 计数），
 * 脚注换成成员数与编排模式，让"这是一个团队"一眼可辨。
 */
import { useTranslation } from "react-i18next";
import { ArrowRight, Pin } from "lucide-react";
import ExpertAvatar from "@/components/ExpertAvatar";
import EmployeeKindAvatar from "@/components/EmployeeKindAvatar";
import { avatarGradient } from "@/utils/avatarGradient";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import { ModeBadge, StatusBadge, VisibilityBadge } from "./employeeBadges";
import styles from "./console.module.less";

/** 堆叠展示的成员上限，超出折叠为 +N。 */
const MAX_STACK = 4;

export interface TeamKindCardProps {
  employee: DigitalEmployee;
  onOpen: (employee: DigitalEmployee) => void;
  actions?: React.ReactNode;
}

export function TeamKindCard({ employee, onOpen, actions }: TeamKindCardProps) {
  const { t } = useTranslation();
  const stacked = employee.members.slice(0, MAX_STACK);
  const rest = employee.members.length - stacked.length;

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
        {/* 团队徽记砖：与成员头像堆叠区分开，避免误读为"某个员工的头像组" */}
        <div
          className="pg-tile"
          data-tone="teal"
          style={{ width: 44, height: 44, borderRadius: 14 }}
        >
          <EmployeeKindAvatar employee={employee} size={44} />
        </div>

        <div className={styles.cardTitleWrap}>
          <div className={styles.nameRow}>
            <span className={styles.name} title={employee.name}>
              {employee.name}
            </span>
            {employee.pinned ? <Pin size={13} className={styles.pinIcon} /> : null}
          </div>
          <div className={styles.sub} title={employee.entity_id}>
            {t("employee.team.memberCount", { count: employee.member_count })}
          </div>
        </div>

        <div
          className={styles.cardActions}
          onClick={(event) => event.stopPropagation()}
        >
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

      {stacked.length > 0 ? (
        <div className={styles.memberStack} aria-hidden="true">
          {stacked.map((member) =>
            member.icon || member.expert_id ? (
              <ExpertAvatar
                key={member.expert_id}
                icon={member.icon}
                expertId={member.expert_id}
                name={member.name}
                size={28}
                className={styles.memberChip}
              />
            ) : (
              <span
                key={member.expert_id}
                className={styles.memberChip}
                style={{
                  width: 28,
                  height: 28,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#fff",
                  fontSize: 12,
                  fontWeight: 600,
                  background: avatarGradient(member.expert_id + member.name),
                }}
              >
                {(member.name || "?").slice(0, 1).toUpperCase()}
              </span>
            ),
          )}
          {rest > 0 ? (
            <span className={styles.memberMore}>+{rest}</span>
          ) : null}
        </div>
      ) : null}

      <div className={styles.badges}>
        <StatusBadge employee={employee} />
        <VisibilityBadge employee={employee} />
        <ModeBadge mode={employee.mode} />
      </div>

      <div className={styles.foot}>
        {employee.model_label ? (
          <span className={styles.chip}>{employee.model_label}</span>
        ) : null}
        {employee.granted_department_names.length > 0 ? (
          <span
            className={styles.chip}
            title={employee.granted_department_names.join("、")}
          >
            {t("employee.team.sharedTo")}{" "}
            {employee.granted_department_names.slice(0, 2).join("、")}
            {employee.granted_department_names.length > 2
              ? ` +${employee.granted_department_names.length - 2}`
              : ""}
          </span>
        ) : null}
        <ArrowRight size={15} className={styles.footArrow} aria-hidden="true" />
      </div>
    </div>
  );
}
