/**
 * AgentActivityTab — 员工动态页（近期活动独立 Tab）。
 *
 * 结构：统计卡行（4 × StatCard，与档案页同源 useBriefStats）+
 * 近期活动时间线（Day/Week/Month 三态日历，ActivityTimeline）。
 * 从档案 Tab 拆出独立成页：档案页聚焦身份与配置，动态页聚焦运行痕迹。
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ActivityTimeline, StatCard } from "@/components/staffdeck";
import { useBriefStats } from "./useBriefStats";
import styles from "./detail.module.less";

/** 大数缩写：12000 → 12k，3400000 → 3.4M。 */
function formatStatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface AgentActivityTabProps {
  /** 员工 agent id（数据域事实来源，useBriefStats 按其拉取）。 */
  aid: string;
}

export default function AgentActivityTab({ aid }: AgentActivityTabProps) {
  const { t } = useTranslation();
  const { stats, loading } = useBriefStats(aid);

  // 近 7 天密度数据映射到 ActivityTimeline（tasks=对话数，feedback 暂无；
  // 当日事件列表由 timeline 提供暂为空）。
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

      {/* 近期活动时间线 */}
      <section className={styles.overviewSection}>
        <h3 className={styles.sectionTitle}>
          {t("agentDetail.recentActivity", "Recent Activity")}
        </h3>
        <ActivityTimeline byDay={byDay} timeline={[]} />
      </section>
    </div>
  );
}
