/**
 * TeamWorkbenchDetail — 专家团工作台详情页（团队分支右栏容器）。
 *
 * 组织视角五 Tab：概览 / 成员与职责 / 协作流程 / 会话 / 运维，与
 * 数字员工的（档案/能力/会话/动态/运维）明确区分。Tab 条由本组件
 * 自带（外壳团队分支下不再渲染员工 Tab 条）；tab 受控于外壳的
 * MemoryRouter 路径解析（URL 是唯一事实来源），切换经 onTabChange
 * 回写路由。会话 Tab 复用外壳已懒加载的 SessionsPage（sessionsSlot
 * 注入，避免重复 lazy 注册）。
 *
 * 降级：团队记录 404/403/其他错误时整页提示（会话语义由左侧聊天
 * 面板独立承载，不受影响）；能力投影/版本/元数据失败由 hook 降级
 * 为空值，仅影响对应区块。
 */
import { lazyImportWithRetry } from "@/utils/lazyWithRetry";
import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { UnderlineTabs } from "@/components/staffdeck";
import type { ReactNode } from "react";
import { Suspense, useCallback } from "react";
import { useTeamDetail } from "./useTeamDetail";
import TeamOverviewTab from "./TeamOverviewTab";
import TeamMembersTab from "./TeamMembersTab";
import TeamWorkflowTab from "./TeamWorkflowTab";
import TeamOpsTab from "./TeamOpsTab";
import type { TeamTabKey } from "./teamTabs";
import workbenchStyles from "../workbench.module.less";

// 运行日志详情：懒加载复用外壳已注册的组件（与 AgentWorkbenchLayout 同源），
// 团队分支的 runId 路由下钻由此承接，不再被团队 Tab 容器截断。
const RunLogDetailPage = lazyImportWithRetry(
  "../../pages/Control/Sessions/RunLogs/RunLogDetailPage",
);

export type { TeamTabKey };

export interface TeamWorkbenchDetailProps {
  /** 运行态 agent id（team_{team_id}），仅用于展示上下文。 */
  aid: string;
  /** 团队配置 id（aid 去掉 team_ 前缀）。 */
  teamId: string;
  /** 后台配置域授权（来自后端 manageable 判定，禁止前端复刻逻辑）。 */
  canManage: boolean;
  /** 当前激活 Tab（外壳按路径解析后传入）。 */
  tab: TeamTabKey;
  /** Tab 切换回写路由（外壳 navigate）。 */
  onTabChange: (key: TeamTabKey) => void;
  /** 会话 Tab 内容槽（外壳注入已懒加载的 SessionsPage）。 */
  sessionsSlot: ReactNode;
  /** 运行日志详情下钻（外壳解析 runId 后传入，非空时覆盖 Tab 内容）。 */
  runId?: string | null;
  /** 外壳 navigate（运维 Tab 行点击跳转运行详情）。 */
  onNavigate?: (path: string) => void;
}

export default function TeamWorkbenchDetail({
  teamId,
  canManage,
  tab,
  onTabChange,
  sessionsSlot,
  runId,
  onNavigate,
}: TeamWorkbenchDetailProps) {
  const { t } = useTranslation();
  const {
    team,
    members,
    versions,
    metadata,
    memberUpdates,
    loading,
    error,
    capabilitiesStatus,
    capabilitiesError,
    versionsStatus,
    versionsError,
    refresh,
  } = useTeamDetail(teamId);

  // 概览 Tab “查看运行”回调：设置 runId 触发下钻详情。
  const handleViewRun = useCallback(
    (runId: string) => {
      // 通过 onNavigate 外壳路由跳转到运行详情（与运维 Tab 行点击同源）
      if (onNavigate) {
        onNavigate(`runs/${runId}`);
      }
    },
    [onNavigate],
  );

  const tabItems = [
    {
      key: "overview" as const,
      label: t("workbench.team.tabOverview", "概览"),
    },
    {
      key: "members" as const,
      label: t("workbench.team.tabMembers", "成员与职责"),
    },
    {
      key: "workflow" as const,
      label: t("workbench.team.tabWorkflow", "协作流程"),
    },
    {
      key: "sessions" as const,
      label: t("workbench.team.tabSessions", "会话"),
    },
    {
      key: "ops" as const,
      label: t("workbench.team.tabOps", "运维"),
    },
  ];

  let content: ReactNode;
  // 运行日志详情下钻优先于 Tab 内容（与外壳非团队分支同源）：
  // runId 存在时无论当前 Tab 是什么，右侧全部交给 RunLogDetailPage。
  if (runId) {
    content = (
      <Suspense fallback={
        <div className={workbenchStyles.emptyWrap}><Spin /></div>
      }>
        <RunLogDetailPage />
      </Suspense>
    );
  } else if (loading) {
    content = (
      <div className={workbenchStyles.emptyWrap}>
        <Spin />
      </div>
    );
  } else if (error || !team) {
    content = (
      <Alert
        type={error?.kind === "forbidden" ? "warning" : "error"}
        showIcon
        message={
          error?.kind === "forbidden"
            ? t(
                "workbench.team.forbidden",
                "无团队配置查看权限（左侧对话不受影响）",
              )
            : t(
                "workbench.team.notFound",
                "团队不存在或已删除（若为普通智能体请从员工列表打开）",
              )
        }
        description={error && error.kind !== "forbidden" ? error.message : undefined}
      />
    );
  } else {
    switch (tab) {
      case "members":
        content = <TeamMembersTab members={members} />;
        break;
      case "workflow":
        content = <TeamWorkflowTab team={team} teamId={teamId} canManage={canManage} metadata={metadata} />;
        break;
      case "sessions":
        content = sessionsSlot;
        break;
      case "ops":
        content = <TeamOpsTab teamId={teamId} onNavigate={onNavigate} />;
        break;
      case "overview":
      default:
        content = (
          <TeamOverviewTab
            team={team}
            members={members}
            versions={versions}
            metadata={metadata}
            memberUpdates={memberUpdates}
            teamId={teamId}
            canManage={canManage}
            capabilitiesStatus={capabilitiesStatus}
            capabilitiesError={capabilitiesError}
            versionsStatus={versionsStatus}
            versionsError={versionsError}
            onViewRun={handleViewRun}
            onRefresh={refresh}
          />
        );
        break;
    }
  }

  return (
    <section className={workbenchStyles.detailPane}>
      <div className={workbenchStyles.tabBar}>
        <UnderlineTabs
          items={tabItems}
          value={tab}
          onChange={(key) => onTabChange(key as TeamTabKey)}
        />
      </div>
      <div className={workbenchStyles.tabContent}>{content}</div>
    </section>
  );
}
