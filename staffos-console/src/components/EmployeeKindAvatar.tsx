/**
 * EmployeeKindAvatar.tsx — 注册表行形象的单一渲染口径（控制台 / 工作台共用）。
 *
 * 三种形态各用不同视觉，避免把团队误读成"某个人"：
 * - expert：DiceBear 形象，种子必须是后端已剥离 `expert_` 前缀的 entity_id，
 *   与工作台、档案页逐字节一致（全站头像种子规范）；
 * - team  ：只回 Users 图标，底色由外层 tile 容器着色（两处容器风格已定）；
 * - agent ：渐变首字符，种子为 agent_id + name。
 */
import { Users } from "lucide-react";
import ExpertAvatar from "@/components/ExpertAvatar";
import { avatarGradient } from "@/utils/avatarGradient";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";

export interface EmployeeKindAvatarProps {
  employee: DigitalEmployee;
  /** 直径（px）。 */
  size?: number;
}

export default function EmployeeKindAvatar({
  employee,
  size = 44,
}: EmployeeKindAvatarProps) {
  if (employee.entity_kind === "team") {
    return <Users size={Math.round(size * 0.46)} />;
  }

  if (employee.entity_kind === "expert") {
    return (
      <ExpertAvatar
        icon={employee.icon}
        expertId={employee.entity_id}
        name={employee.name}
        size={size}
      />
    );
  }

  return (
    <div
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: "50%",
        background: avatarGradient(employee.agent_id + employee.name),
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: Math.round(size * 0.38),
        fontWeight: 600,
      }}
    >
      {(employee.name || "?").slice(0, 1).toUpperCase()}
    </div>
  );
}
