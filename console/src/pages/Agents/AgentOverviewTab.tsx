/**
 * AgentOverviewTab.tsx — 员工概览（档案中心首页）。
 *
 * 结构：统计卡行（4 × StatCard，数据来自 /agent-stats/summary-brief）→
 * 能力资产入口卡（按员工能力过滤）→ 员工档案文档区（角色定位 + 快捷
 * 指令 chips）→ 近期活动（ActivityTimeline 周密度视图）。
 *
 * 诚实数据原则：后端未就绪的指标（好评率）一律显示占位，不造假。
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Cable,
  Clock,
  FolderOpen,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { ActivityTimeline, StatCard } from "@/components/staffdeck";
import type { AgentSummary } from "@/api/types/agents";
import type { DetailTab } from "./EmployeeProfileAside";
import { useBriefStats } from "./useBriefStats";
import styles from "./detail.module.less";

/** 能力资产入口卡定义：key 对应借壳 Tab 键。 */
const ABILITY_CARDS: Array<{
  key: string;
  labelKey: string;
  fallback: string;
  icon: LucideIcon;
}> = [
  { key: "files", labelKey: "nav.files", fallback: "Files", icon: FolderOpen },
  { key: "skills", labelKey: "nav.skills", fallback: "Skills", icon: Sparkles },
  { key: "tools", labelKey: "nav.tools", fallback: "Tools", icon: Wrench },
  { key: "mcp", labelKey: "nav.mcp", fallback: "MCP", icon: Cable },
  { key: "cron-jobs", labelKey: "nav.cronJobs", fallback: "Scheduled Tasks", icon: Clock },
];

/** 大数缩写：12000 → 12k，3400000 → 3.4M。 */
function formatStatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface AgentOverviewTabProps {
  /** agents 尚未加载完成时为 undefined，此时仅渲染 aid。 */
  agent: AgentSummary | undefined;
  aid: string;
  /** 能力过滤后的可见 Tab，用于能力入口卡展示与跳转。 */
  visibleTabs: DetailTab[];
  /** 发起 AI 调优（跳对话 Tab 并预填指令）。 */
  onAiTune: (prompt: string) => void;
  /** 打开员工域子 Tab（沿用借壳导航）。 */
  onOpenTab: (key: string) => void;
}

export default function AgentOverviewTab({
  agent,
  aid,
  visibleTabs,
  onAiTune,
  onOpenTab,
}: AgentOverviewTabProps) {
  const { t } = useTranslation();
  const { stats, loading } = useBriefStats(aid);

  // 能力入口卡 = 预定义卡 ∩ 能力过滤后的可见 Tab。
  const abilityCards = useMemo(
    () =>
      ABILITY_CARDS.filter((card) =>
        visibleTabs.some((tab) => tab.key === card.key),
      ),
    [visibleTabs],
  );

  const quickPrompts = useMemo(
    () => [
      {
        key: "profile",
        text: t(
          "agentDetail.promptTuneProfile",
          "Optimize this employee's profile",
        ),
      },
      {
        key: "skills",
        text: t(
          "agentDetail.promptAddSkills",
          "Add suitable skills for this employee",
        ),
      },
      {
        key: "improve",
        text: t("agentDetail.promptImprove", "Improve this employee"),
      },
    ],
    [t],
  );

  // 近 7 天密度数据映射到 ActivityTimeline（tasks=对话数，feedback 暂无）。
  const byDay = useMemo(
    () =>
      (stats?.recent_daily ?? []).map((d) => ({
        date: d.date,
        tasks: d.chats,
        feedback: 0,
      })),
    [stats],
  );

  const statCells = [
    {
      label: t("agentDetail.statTodayChats", "Today's chats"),
      value: stats ? stats.today_chats : null,
    },
    {
      label: t("agentDetail.statTotalChats", "Total chats"),
      value: stats ? stats.total_chats : null,
    },
    {
      label: t("agentDetail.statActiveSessions", "Active sessions"),
      value: stats ? stats.active_sessions : null,
    },
    {
      label: t("agentDetail.statTokens", "Token usage"),
      value: stats ? formatStatNumber(stats.total_tokens) : null,
    },
  ];

  return (
    <div className={styles.overviewWrap}>
      {/* 统计卡行 */}
      <div className={styles.statRow}>
        {statCells.map((cell) => (
          <StatCard
            key={cell.label}
            value={loading && stats === null ? "…" : cell.value ?? "—"}
            label={cell.label}
          />
        ))}
      </div>

      {/* 能力资产入口卡 */}
      {abilityCards.length > 0 && (
        <section className={styles.overviewSection}>
          <h3 className={styles.sectionTitle}>
            {t("agentDetail.abilityAssets", "Capability Assets")}
          </h3>
          <div className={styles.abilityRow}>
            {abilityCards.map((card) => {
              const Icon = card.icon;
              return (
                <button
                  key={card.key}
                  type="button"
                  className={styles.abilityCard}
                  onClick={() => onOpenTab(card.key)}
                >
                  <Icon size={18} className={styles.abilityIcon} />
                  <span className={styles.abilityName}>
                    {t(card.labelKey, card.fallback)}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* 员工档案文档区 */}
      <section className={styles.overviewSection}>
        <h3 className={styles.sectionTitle}>
          {t("agentDetail.profile", "Employee Profile")}
        </h3>
        <div className={`${styles.profileDocCard} sd-card`}>
          <h4 className={styles.docHeading}>
            {t("agentDetail.rolePosition", "Role & Positioning")}
          </h4>
          <p className={styles.docBody}>
            {agent?.description ||
              t(
                "agentDetail.rolePositionPlaceholder",
                "No description yet. Edit the employee profile to add one.",
              )}
          </p>
          <h4 className={styles.docHeading}>
            {t("agentDetail.quickPrompts", "Quick Prompts")}
          </h4>
          <div className={styles.chipRow}>
            {quickPrompts.map((prompt) => (
              <button
                key={prompt.key}
                type="button"
                className={styles.promptChip}
                onClick={() => onAiTune(prompt.text)}
              >
                {prompt.text}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* 近期活动（周密度视图；当日事件列表由 timeline 提供暂为空） */}
      <section className={styles.overviewSection}>
        <h3 className={styles.sectionTitle}>
          {t("agentDetail.recentActivity", "Recent Activity")}
        </h3>
        <ActivityTimeline byDay={byDay} timeline={[]} />
      </section>
    </div>
  );
}
