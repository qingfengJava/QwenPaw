/**
 * TeamOrgChart — 专家团层级组织架构图（概览 Tab）。
 *
 * Leader 卡片居中在上、连接线表达汇报关系、成员卡片网格在下；
 * 每张卡片带角色徽标与职责摘要。未发布成员显式标红并给出不可
 * 执行原因（与能力矩阵同口径：声明≠可执行）。纯展示组件，数据
 * 全部来自后端能力投影，前端不拼装业务语义。
 */
import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { avatarGradient } from "@/utils/avatarGradient";
import type { TeamCapabilityMember } from "../../../../api/modules/admin";
import styles from "./teamDetail.module.less";

export interface TeamOrgChartProps {
  members: TeamCapabilityMember[];
}

/** 成员首字符渐变头像（capabilities 投影无 icon 字段，与团队卡降级态同规则）。 */
function MemberAvatar({ member }: { member: TeamCapabilityMember }) {
  const name = member.name || member.expert_id;
  return (
    <span
      aria-hidden="true"
      style={{
        width: 36,
        height: 36,
        borderRadius: 12,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontSize: 14,
        fontWeight: 600,
        flex: "0 0 auto",
        background: avatarGradient(member.expert_id + name),
      }}
    >
      {(name || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

function MemberCard({
  member,
  roleLabel,
  isLead,
}: {
  member: TeamCapabilityMember;
  roleLabel: string;
  isLead: boolean;
}) {
  const { t } = useTranslation();
  const published = member.published;
  return (
    <div
      className={`${styles.memberCard} ${
        published ? "" : styles.memberCardBlocked
      }`}
      style={isLead ? { minWidth: 240 } : undefined}
    >
      <MemberAvatar member={member} />
      <div className={styles.memberInfo}>
        <div className={styles.memberName} title={member.name || member.expert_id}>
          {member.name || member.expert_id}
        </div>
        <div className={styles.memberTitle}>
          <Tag
            color={isLead ? "gold" : "default"}
            style={{ marginRight: 6 }}
          >
            {roleLabel}
          </Tag>
          {member.title}
        </div>
        {member.role_hint ? (
          <div className={styles.memberHint}>{member.role_hint}</div>
        ) : null}
        {!published && member.unavailable_reason ? (
          <div className={styles.memberBlockedReason}>
            {t("workbench.team.unavailable", "不可执行：{{reason}}", {
              reason: member.unavailable_reason,
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function TeamOrgChart({ members }: TeamOrgChartProps) {
  const { t } = useTranslation();
  const leadLabel = t("workbench.team.roleLead", "主理人");
  const memberLabel = t("workbench.team.roleMember", "成员");

  // 组织层级由 member_role 派生（渲染期计算，不落状态）。
  const leads = members.filter((m) => m.member_role === "lead");
  const others = members.filter((m) => m.member_role !== "lead");

  if (members.length === 0) {
    return null;
  }

  return (
    <div className={styles.orgChart}>
      {leads.map((lead) => (
        <div key={lead.expert_id} className={styles.leaderRow}>
          <MemberCard member={lead} roleLabel={leadLabel} isLead />
        </div>
      ))}
      {leads.length > 0 && others.length > 0 ? (
        <div className={styles.connector} aria-hidden="true" />
      ) : null}
      {others.length > 0 ? (
        <div className={styles.memberGrid}>
          {others.map((member) => (
            <MemberCard
              key={member.expert_id}
              member={member}
              roleLabel={memberLabel}
              isLead={false}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
