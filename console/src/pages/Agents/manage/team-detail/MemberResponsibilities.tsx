/**
 * MemberResponsibilities — 成员职责与有效能力矩阵（团队详情页 Tab）。
 *
 * 数据全部来自后端能力投影（capabilities）：声明≠可执行，未发布
 * 成员在矩阵中显式标红并给出不可执行原因；技能/工具/知识库/SOP
 * 以数量徽标呈现，详情看员工管理页（职责单一：此处只回答"谁能
 * 做什么、凭什么"）。
 */
import { Alert, Table, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { TeamCapabilityMember } from "../../../../api/modules/admin/expertTeams";

export interface MemberResponsibilitiesProps {
  members: TeamCapabilityMember[];
  loading: boolean;
  error: string;
}

export default function MemberResponsibilities({
  members,
  loading,
  error,
}: MemberResponsibilitiesProps) {
  const { t } = useTranslation();

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("admin.teamDetail.capabilityLoadFailed", "能力投影加载失败")}
        description={error}
      />
    );
  }

  return (
    <div>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {t(
          "admin.teamDetail.capabilityHint",
          "能力矩阵展示每个成员的职责角色与实际可执行能力（已发布 + 已挂载的技能/工具/知识库）。声明了能力但未发布的成员无法被派发任务。",
        )}
      </Typography.Paragraph>
      <Table<TeamCapabilityMember>
        rowKey="expert_id"
        size="small"
        loading={loading}
        dataSource={members}
        pagination={false}
        columns={[
          {
            title: t("admin.teamDetail.colMember", "成员"),
            dataIndex: "name",
            render: (name: string, row) => (
              <div>
                <div>{name || row.expert_id}</div>
                {row.title && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {row.title}
                  </Typography.Text>
                )}
              </div>
            ),
          },
          {
            title: t("admin.teamDetail.colRole", "职责角色"),
            dataIndex: "member_role",
            width: 110,
            render: (role: string) =>
              role === "lead" ? (
                <Tag color="gold">{t("admin.teamDetail.roleLead", "主理人")}</Tag>
              ) : (
                <Tag>{t("admin.teamDetail.roleMember", "成员")}</Tag>
              ),
          },
          {
            title: t("admin.teamDetail.colHint", "职责提示"),
            dataIndex: "role_hint",
            render: (hint: string) => hint || "—",
          },
          {
            title: t("admin.teamDetail.colSkills", "技能/工具/知识库"),
            key: "mounts",
            width: 240,
            render: (_, row) => (
              <span>
                <Tag>{t("admin.teamDetail.skillsN", "技能 ×{{n}}", { n: row.skills.length })}</Tag>
                <Tag>{t("admin.teamDetail.toolsN", "工具 ×{{n}}", { n: row.tools.length })}</Tag>
                <Tag>{t("admin.teamDetail.kbN", "知识库 ×{{n}}", { n: row.kb_ids.length })}</Tag>
                <Tag>{t("admin.teamDetail.sopN", "SOP ×{{n}}", { n: row.sops.length })}</Tag>
              </span>
            ),
          },
          {
            title: t("admin.teamDetail.colStatus", "可执行"),
            dataIndex: "published",
            width: 180,
            render: (published: boolean, row) =>
              published ? (
                <Tag color="green">{t("admin.teamDetail.published", "已发布")}</Tag>
              ) : (
                <Tag color="red" title={row.unavailable_reason}>
                  {t("admin.teamDetail.unpublished", "未发布")}
                  {row.unavailable_reason ? `：${row.unavailable_reason}` : ""}
                </Tag>
              ),
          },
        ]}
      />
    </div>
  );
}
