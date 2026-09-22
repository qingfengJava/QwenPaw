/**
 * TeamMembersTab — 成员与职责（团队详情页 Tab，工作台视角薄壳）。
 *
 * 直接复用管理端能力矩阵 MemberResponsibilities（props 完全兼容）：
 * 数据全部来自后端能力投影，声明≠可执行，未发布成员显式标红并给
 * 出不可执行原因。此处不新增展示语义，避免两处矩阵漂移。
 */
import MemberResponsibilities from "../../manage/team-detail/MemberResponsibilities";
import type { TeamCapabilityMember } from "../../../../api/modules/admin";

export interface TeamMembersTabProps {
  members: TeamCapabilityMember[];
}

export default function TeamMembersTab({ members }: TeamMembersTabProps) {
  return (
    <MemberResponsibilities members={members} loading={false} error="" />
  );
}
