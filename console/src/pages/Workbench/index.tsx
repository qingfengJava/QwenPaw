/**
 * Workbench/index.tsx — 平台工作台（20260914 质感升级）。
 *
 * 页面结构（四段式，建立"画布 → 面 → tile"三层视觉层级）：
 *   Hero（时间问候 + 渐变标题 + 定位副标 + 双 CTA + 右侧团队星群）→
 *   指标条（数字员工 / 运行中 / 未读消息 / 待审批，四项真实运行数据）→
 *   数字员工网格（DiceBear 形象 + 状态胶囊 + 描述 + 模型脚注）→
 *   快捷入口（彩色 icon tile + 说明文案）。
 *
 * 数据诚实原则：指标全部来自本页真实请求（agents store / inbox events /
 * push messages），后端未提供平台级聚合统计，因此不展示任何会话/Token
 * 类"全局汇总"，缺失即显示占位符。原「收件箱」横幅的能力已并入指标条
 * （未读数 + 一键跳转 /inbox），不再单独占一行。
 */
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type HTMLAttributes,
} from "react";
import { Button } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import {
  ArrowRight,
  Bell,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Globe,
  LayoutGrid,
  MessageSquare,
  Pin,
  Plus,
  ShieldAlert,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { api } from "@/api";
import { useAgentStore } from "@/stores/agentStore";
import { useExpertIcons } from "@/hooks/useExpertIcons";
import { isExpertAgentId } from "@/api/modules/xianFeedback";
import ExpertAvatar from "@/components/ExpertAvatar";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentStartupStatus, AgentSummary } from "@/api/types/agents";
import styles from "./workbench.module.less";

/** 启动状态 → 胶囊色调（文案沿用 agent.status.* 字典）。 */
const STATUS_TONE: Record<AgentStartupStatus, string> = {
  running: "green",
  starting: "blue",
  pending: "blue",
  failed: "red",
  disabled: "gray",
};

/** 快捷入口：彩色 tile 区分功能域，tone 只驱动底色，语义仍由文案承担。 */
const QUICK_LINKS: ReadonlyArray<{
  path: string;
  tone: string;
  Icon: LucideIcon;
  labelKey: string;
  descKey: string;
}> = [
  {
    path: "/channels",
    tone: "blue",
    Icon: Globe,
    labelKey: "nav.channels",
    descKey: "workbench.quickChannelsDesc",
  },
  {
    path: "/models",
    tone: "violet",
    Icon: Cpu,
    labelKey: "nav.models",
    descKey: "workbench.quickModelsDesc",
  },
  {
    path: "/skill-pool",
    tone: "teal",
    Icon: Sparkles,
    labelKey: "nav.skillPool",
    descKey: "workbench.quickSkillPoolDesc",
  },
  {
    path: "/apps",
    tone: "amber",
    Icon: LayoutGrid,
    labelKey: "nav.apps",
    descKey: "workbench.quickAppsDesc",
  },
];

/**
 * 入场错峰序号写入 --wb-seq，由 CSS 换算 animation-delay。
 * 序号封顶 8：员工较多时避免尾部卡片延迟近 1 秒才出现。
 */
function seqStyle(index: number): CSSProperties {
  return { "--wb-seq": Math.min(index, 8) } as CSSProperties;
}

/** div[role=button] 承载可点击卡片：补齐与原生按钮等价的键盘行为。 */
function pressable(onClick?: () => void): HTMLAttributes<HTMLDivElement> {
  if (!onClick) return {};
  return {
    role: "button",
    tabIndex: 0,
    onClick,
    onKeyDown: (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onClick();
      }
    },
  };
}

/** 平台工作台：数字员工总览 + 运行指标 + 快捷入口（平台 IA 阶段 4）。 */
export default function WorkbenchPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { agents, refreshAgents } = useAgentStore();
  const expertIcons = useExpertIcons();
  // null = 请求未回来，渲染占位符，避免把"加载中"误读成"0 条"
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [approvalCount, setApprovalCount] = useState<number | null>(null);

  // 工作台是常见落地页，store 可能还没有员工缓存，挂载时拉一次
  // （refreshAgents 内建 promise 去重，与其它页并发调用安全）
  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  // 收件箱未读总数（total 为分页前计数；轮询逻辑归 Inbox 页与侧栏徽标）
  useEffect(() => {
    let cancelled = false;
    api
      .getInboxEvents({ unread_only: true, limit: 50 })
      .then((res) => {
        if (cancelled) return;
        setUnreadCount(res?.total ?? res?.events?.length ?? 0);
      })
      .catch(() => {
        if (!cancelled) setUnreadCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 待审批数：/console/push-messages 返回全量 pending approvals（跨员工聚合）
  useEffect(() => {
    let cancelled = false;
    api
      .getPushMessages()
      .then((res) => {
        if (!cancelled) setApprovalCount(res?.pending_approvals?.length ?? 0);
      })
      .catch(() => {
        if (!cancelled) setApprovalCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 已启用的员工排前面，其余按原有顺序
  const sortedAgents = useMemo(() => {
    const enabled = agents.filter((agent) => agent.enabled);
    const disabled = agents.filter((agent) => !agent.enabled);
    return [...enabled, ...disabled];
  }, [agents]);

  const runningCount = useMemo(
    () => agents.filter((agent) => agent.startup_status === "running").length,
    [agents],
  );

  // 时间问候 + 本地化日期行（Intl 跟随当前语言，不写死日期格式）
  const { greeting, dateLine } = useMemo(() => {
    const now = dayjs();
    const hour = now.hour();
    const bucket =
      hour < 5
        ? "lateNight"
        : hour < 11
          ? "morning"
          : hour < 14
            ? "noon"
            : hour < 18
              ? "afternoon"
              : "evening";
    let formatted = now.format("YYYY-MM-DD dddd");
    try {
      formatted = new Intl.DateTimeFormat(i18n.language, {
        month: "long",
        day: "numeric",
        weekday: "long",
      }).format(now.toDate());
    } catch {
      // 语言标签不被 Intl 支持时保留 dayjs 兜底格式，不阻塞渲染
    }
    return { greeting: t(`workbench.greeting.${bucket}`), dateLine: formatted };
  }, [i18n.language, t]);

  // Hero 右侧团队星群：首位领像 + 最多 3 位随行 + 溢出计数（全部真实员工）
  const leadAgent = sortedAgents[0];
  const clusterAgents = sortedAgents.slice(1, 4);
  const restCount = Math.max(sortedAgents.length - clusterAgents.length - 1, 0);

  /** 员工形象：expert_ 前缀剥离后作 DiceBear 种子，与详情页/列表页同源。 */
  const renderAvatar = (agent: AgentSummary, size: number) => {
    const expertId = isExpertAgentId(agent.id);
    const name = getAgentDisplayName(agent, t);
    return (
      <ExpertAvatar
        icon={expertId ? expertIcons[expertId] : undefined}
        expertId={expertId || agent.id}
        name={name}
        size={size}
      />
    );
  };

  const metrics: ReadonlyArray<{
    key: string;
    tone: string;
    Icon: LucideIcon;
    label: string;
    value: number | null;
    to?: string;
  }> = [
    {
      key: "employees",
      tone: "blue",
      Icon: Users,
      label: t("workbench.metricEmployees"),
      value: agents.length,
      to: "/agents",
    },
    {
      key: "running",
      tone: "green",
      Icon: CheckCircle2,
      label: t("workbench.metricRunning"),
      value: runningCount,
    },
    {
      key: "unread",
      tone: (unreadCount ?? 0) > 0 ? "amber" : "gray",
      Icon: Bell,
      label: t("workbench.metricUnread"),
      value: unreadCount,
      to: "/inbox",
    },
    {
      key: "approvals",
      tone: (approvalCount ?? 0) > 0 ? "red" : "gray",
      Icon: ShieldAlert,
      label: t("workbench.metricApprovals"),
      value: approvalCount,
      to: "/inbox",
    },
  ];

  return (
    <div className={styles.workbench}>
      <div className={styles.inner}>
        {/* ── Hero：页面身份 + 主行动 ───────────────────────────────── */}
        <section className={styles.hero}>
          <span className={styles.heroGlow} aria-hidden="true" />
          <div className={styles.heroMain}>
            <p className={styles.heroEyebrow}>
              <span className={styles.heroEyebrowDot} aria-hidden="true" />
              {dateLine}
            </p>
            <h1 className={styles.heroTitle}>
              {greeting}，
              <span className={styles.heroTitleAccent}>
                {t("workbench.heroTitleAccent")}
              </span>
            </h1>
            <p className={styles.heroSub}>{t("workbench.heroSubtitle")}</p>
            <div className={styles.heroActions}>
              <Button
                type="primary"
                className={styles.heroPrimary}
                icon={<MessageSquare size={16} />}
                onClick={() => navigate("/chat")}
              >
                {t("workbench.startChat")}
              </Button>
              <Button
                className={styles.heroGhost}
                icon={<Plus size={16} />}
                onClick={() => navigate("/agents")}
              >
                {t("agent.create")}
              </Button>
            </div>
          </div>

          {/* 团队星群：真实数字员工形象组成，无员工时退化为品牌图标 */}
          <div className={styles.heroVisual} aria-hidden="true">
            <span className={styles.heroVisualOrb} />
            {runningCount > 0 ? (
              <span className={styles.heroBadge}>
                <span className={styles.heroBadgeDot} />
                {t("workbench.onlineNow", { n: runningCount })}
              </span>
            ) : null}
            <span className={styles.heroLead}>
              <span className={styles.heroLeadInner}>
                {leadAgent ? (
                  renderAvatar(leadAgent, 92)
                ) : (
                  <Sparkles size={34} />
                )}
              </span>
            </span>
            {clusterAgents.length > 0 ? (
              <span className={styles.heroCluster}>
                {clusterAgents.map((agent) => (
                  <span key={agent.id} className={styles.heroClusterItem}>
                    {renderAvatar(agent, 36)}
                  </span>
                ))}
                {restCount > 0 ? (
                  <span className={styles.heroClusterMore}>+{restCount}</span>
                ) : null}
              </span>
            ) : null}
          </div>
        </section>

        {/* ── 指标条：本页真实请求汇总，替代原收件箱横幅 ─────────────── */}
        <section
          className={styles.metrics}
          aria-label={t("workbench.metricsAria")}
        >
          {metrics.map((metric, index) => {
            const { to } = metric;
            return (
              <div
                key={metric.key}
                className={`${styles.metricCard} ${styles.rise}`}
                style={seqStyle(index + 1)}
                data-tone={metric.tone}
                data-clickable={to ? "true" : "false"}
                {...pressable(to ? () => navigate(to) : undefined)}
              >
                <span className={styles.metricIcon}>
                  <metric.Icon size={19} />
                </span>
                <span className={styles.metricBody}>
                  <strong className={styles.metricValue}>
                    {metric.value ?? "—"}
                  </strong>
                  <span className={styles.metricLabel}>{metric.label}</span>
                </span>
                {to ? (
                  <ChevronRight size={16} className={styles.metricArrow} />
                ) : null}
              </div>
            );
          })}
        </section>

        {/* ── 数字员工网格 ──────────────────────────────────────────── */}
        <section className={styles.section}>
          <header className={styles.sectionHead}>
            <div className={styles.sectionTitleGroup}>
              <span className={styles.sectionRule} aria-hidden="true" />
              <h2 className={styles.sectionTitle}>{t("nav.employees")}</h2>
              <span className={styles.sectionCount}>{agents.length}</span>
            </div>
            <span
              className={styles.sectionLink}
              {...pressable(() => navigate("/agents"))}
            >
              {t("workbench.viewAllEmployees")}
              <ArrowRight size={13} />
            </span>
          </header>

          <div className={styles.agentGrid}>
            {sortedAgents.map((agent, index) => {
              const status = agent.startup_status ?? (
                agent.enabled ? "pending" : "disabled"
              );
              const statusKey = `agent.status.${status}`;
              const modelLabel =
                agent.active_model?.model || agent.backend_model || "";
              return (
                <div
                  key={agent.id}
                  className={`${styles.agentCard} ${styles.rise} ${
                    agent.enabled ? "" : styles.agentCardDisabled
                  }`}
                  style={seqStyle(index + 1)}
                  {...pressable(() => navigate(`/agents/${agent.id}`))}
                >
                  <span className={styles.agentCardGlow} aria-hidden="true" />
                  <div className={styles.agentCardHead}>
                    <span className={styles.agentCardAvatar}>
                      {renderAvatar(agent, 44)}
                    </span>
                    <span className={styles.agentCardTitleBlock}>
                      <span className={styles.agentCardName}>
                        {getAgentDisplayName(agent, t)}
                        {agent.pinned ? (
                          <Pin size={12} className={styles.agentCardPin} />
                        ) : null}
                      </span>
                      <span className={styles.pill} data-tone={STATUS_TONE[status]}>
                        <span className={styles.pillDot} aria-hidden="true" />
                        {t(statusKey)}
                      </span>
                    </span>
                    <ArrowRight
                      size={15}
                      className={styles.agentCardArrow}
                      aria-hidden="true"
                    />
                  </div>

                  {agent.description ? (
                    <div className={styles.agentCardDesc}>
                      {agent.description}
                    </div>
                  ) : (
                    <div
                      className={`${styles.agentCardDesc} ${styles.agentCardDescEmpty}`}
                    >
                      {t("workbench.noDescription")}
                    </div>
                  )}

                  <div className={styles.agentCardFoot}>
                    {modelLabel ? (
                      <span className={styles.agentChip}>
                        <Cpu size={11} className={styles.agentChipIcon} />
                        {modelLabel}
                      </span>
                    ) : null}
                    <span className={styles.agentChip}>
                      {agent.backend === "qwenpaw"
                        ? t("agent.backend.nativeBadge")
                        : agent.backend}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* 创建卡：与员工卡同尺寸占位，保持网格节奏 */}
            <div
              className={`${styles.agentCard} ${styles.agentCardCreate} ${styles.rise}`}
              style={seqStyle(sortedAgents.length + 1)}
              {...pressable(() => navigate("/agents"))}
            >
              <span className={styles.agentCardCreateIcon}>
                <Plus size={18} />
              </span>
              <span className={styles.agentCardName}>
                {t("agent.create")}
              </span>
              <span className={styles.quickDesc}>
                {t("workbench.createHint")}
              </span>
            </div>
          </div>
        </section>

        {/* ── 快捷入口 ──────────────────────────────────────────────── */}
        <section className={styles.section}>
          <header className={styles.sectionHead}>
            <div className={styles.sectionTitleGroup}>
              <span className={styles.sectionRule} aria-hidden="true" />
              <h2 className={styles.sectionTitle}>{t("workbench.quickLinks")}</h2>
            </div>
          </header>

          <div className={styles.quickGrid}>
            {QUICK_LINKS.map(({ path, tone, Icon, labelKey, descKey }, index) => (
              <div
                key={path}
                className={`${styles.quickCard} ${styles.rise}`}
                style={seqStyle(index + 1)}
                data-tone={tone}
                {...pressable(() => navigate(path))}
              >
                <span className={styles.quickIcon}>
                  <Icon size={19} />
                </span>
                <span className={styles.quickBody}>
                  <span className={styles.quickTitle}>{t(labelKey)}</span>
                  <span className={styles.quickDesc}>{t(descKey)}</span>
                </span>
                <ChevronRight size={16} className={styles.quickArrow} />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
