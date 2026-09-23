/**
 * Workbench/index.tsx — 平台工作台（20260914 质感升级）。
 *
 * 页面结构（四段式，建立"画布 → 面 → tile"三层视觉层级）：
 *   Hero（时间问候 + 渐变标题 + 定位副标 + 双 CTA + 右侧团队星群）→
 *   指标条（数字员工 / 运行中 / 未读消息 / 待审批，四项真实运行数据）→
 *   员工网格（按形态分区：智能体与专家团各一面，团卡带成员堆叠与编排模式）→
 *   快捷入口（彩色 icon tile + 说明文案）。
 *
 * 数据单一来源：员工清单、形态、部门归属与可见范围全部来自
 * `GET /agents/registry`（与数字员工控制台同一接口），本页不再自行拼语义。
 * 数据诚实原则：指标全部来自本页真实请求（registry / inbox events /
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
  Building2,
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
import ExpertAvatar from "@/components/ExpertAvatar";
import EmployeeKindAvatar from "@/components/EmployeeKindAvatar";
import { useEmployeeRegistry } from "@/hooks/useEmployeeRegistry";
import { openAgentWorkbench } from "@/utils/openAgentWorkbench";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import styles from "./workbench.module.less";

/** 运行状态 → 胶囊色调（文案沿用 agent.status.* 字典）。 */
const STATUS_TONE: Record<string, string> = {
  running: "green",
  starting: "blue",
  pending: "blue",
  failed: "red",
  disabled: "gray",
};

/** 可见范围 → 胶囊色调（部门专属需被注意到，故用琥珀）。 */
const VISIBILITY_TONE: Record<string, string> = {
  org: "gray",
  department: "amber",
  private: "gray",
};

/** 专家团卡展示的成员头像上限，超出折叠为 +N。 */
const MAX_MEMBER_STACK = 4;

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
  // 员工清单与控制台同一数据源：一次请求同时带来形态、部门与可见范围
  const { rows: employees, stats, loading } = useEmployeeRegistry();
  // null = 请求未回来，渲染占位符，避免把"加载中"误读成"0 条"
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [approvalCount, setApprovalCount] = useState<number | null>(null);

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

  /** 启用优先，其余保持注册表顺序（pinned 已由后端装配阶段排好）。 */
  const ranked = (rows: DigitalEmployee[]) => [
    ...rows.filter((row) => row.enabled),
    ...rows.filter((row) => !row.enabled),
  ];

  // 形态分区：「智能体」（原生 + 数字员工）与「专家团」各一面，不再混排
  const agentRows = useMemo(
    () => ranked(employees.filter((row) => row.entity_kind !== "team")),
    [employees],
  );
  const teamRows = useMemo(
    () => ranked(employees.filter((row) => row.entity_kind === "team")),
    [employees],
  );
  const rankedEmployees = useMemo(
    () => [...agentRows, ...teamRows],
    [agentRows, teamRows],
  );

  const runningCount = stats.running;

  /**
   * 卡片点击：可用则新标签页开工作台，否则跳控制台。
   *
   * 未物化的草稿员工在控制台里有能力配置入口，工作台不复制权限判断。
   */
  const openEmployee = (employee: DigitalEmployee) => {
    if (employee.usable) {
      openAgentWorkbench(employee.agent_id);
      return;
    }
    navigate("/agents");
  };

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
  const leadEmployee = rankedEmployees[0];
  const clusterEmployees = rankedEmployees.slice(1, 4);
  const restCount = Math.max(
    rankedEmployees.length - clusterEmployees.length - 1,
    0,
  );

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
      value: employees.length,
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

  /**
   * 员工卡（两个形态区共用同一骨架）：差异只在头部形象与成员堆叠。
   *
   * 治理徽标（部门 / 可见范围）仅在已治理时出现：未归属不留占位，
   * 避免把默认语义读成“已做过治理决策”。
   */
  const renderEmployeeCard = (employee: DigitalEmployee, index: number) => {
    const isTeam = employee.entity_kind === "team";
    const stacked = employee.members.slice(0, MAX_MEMBER_STACK);
    const restMembers = employee.members.length - stacked.length;
    const statusLabel =
      employee.lifecycle_status === "draft"
        ? t("employee.lifecycle.draft")
        : employee.lifecycle_status === "archived"
          ? t("employee.lifecycle.archived")
          : t(
              `agent.status.${
                employee.startup_status ||
                (employee.enabled ? "pending" : "disabled")
              }`,
            );
    const statusTone =
      employee.lifecycle_status === "draft"
        ? "blue"
        : employee.lifecycle_status === "archived"
          ? "gray"
          : STATUS_TONE[
              employee.startup_status ||
                (employee.enabled ? "pending" : "disabled")
            ] ?? "gray";

    return (
      <div
        key={employee.agent_id}
        className={`${styles.agentCard} ${styles.rise} ${
          employee.enabled ? "" : styles.agentCardDisabled
        }`}
        style={seqStyle(index + 1)}
        {...pressable(() => openEmployee(employee))}
      >
        <span className={styles.agentCardGlow} aria-hidden="true" />
        <div className={styles.agentCardHead}>
          <span className={styles.agentCardAvatar}>
            <EmployeeKindAvatar employee={employee} size={44} />
          </span>
          <span className={styles.agentCardTitleBlock}>
            <span className={styles.agentCardName}>
              {employee.name}
              {employee.pinned ? (
                <Pin size={12} className={styles.agentCardPin} />
              ) : null}
            </span>
            <span className={styles.pill} data-tone={statusTone}>
              <span className={styles.pillDot} aria-hidden="true" />
              {statusLabel}
            </span>
          </span>
          <ArrowRight
            size={15}
            className={styles.agentCardArrow}
            aria-hidden="true"
          />
        </div>

        {isTeam && stacked.length > 0 ? (
          <div className={styles.memberRow} aria-hidden="true">
            {stacked.map((member) => (
              <ExpertAvatar
                key={member.expert_id}
                icon={member.icon}
                expertId={member.expert_id}
                name={member.name}
                size={26}
                className={styles.memberChip}
              />
            ))}
            {restMembers > 0 ? (
              <span className={styles.memberMore}>+{restMembers}</span>
            ) : null}
          </div>
        ) : null}

        <div
          className={`${styles.agentCardDesc} ${
            employee.description ? "" : styles.agentCardDescEmpty
          }`}
        >
          {employee.description || t("workbench.noDescription")}
        </div>

        {employee.department_name || employee.governed ? (
          <div className={styles.agentCardBadges}>
            {employee.department_name ? (
              <span
                className={styles.pill}
                data-tone="blue"
                title={employee.department_name}
              >
                <Building2 size={10} />
                {employee.department_name}
              </span>
            ) : null}
            {employee.governed ? (
              <span
                className={styles.pill}
                data-tone={VISIBILITY_TONE[employee.visibility] ?? "gray"}
              >
                {t(`employee.visibility.${employee.visibility}`)}
              </span>
            ) : null}
            {isTeam && employee.mode ? (
              <span className={styles.pill} data-tone="teal">
                {t(`employee.teamMode.${employee.mode}`)}
              </span>
            ) : null}
          </div>
        ) : null}

        <div className={styles.agentCardFoot}>
          {employee.model_label ? (
            <span className={styles.agentChip} title={employee.model_label}>
              <Cpu size={11} className={styles.agentChipIcon} />
              {employee.model_label}
            </span>
          ) : null}
          {isTeam ? (
            <span className={styles.agentChip}>
              {t("employee.team.memberCount", { count: employee.member_count })}
            </span>
          ) : (
            <span className={styles.agentChip}>
              {employee.backend === "qwenpaw"
                ? t("agent.backend.nativeBadge")
                : t(`employee.kind.${employee.entity_kind}`)}
            </span>
          )}
        </div>
      </div>
    );
  };

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
                {leadEmployee ? (
                  <EmployeeKindAvatar employee={leadEmployee} size={92} />
                ) : (
                  <Sparkles size={34} />
                )}
              </span>
            </span>
            {clusterEmployees.length > 0 ? (
              <span className={styles.heroCluster}>
                {clusterEmployees.map((employee) => (
                  <span
                    key={employee.agent_id}
                    className={styles.heroClusterItem}
                  >
                    <EmployeeKindAvatar employee={employee} size={36} />
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

        {/* ── 智能体（原生智能体 + 业务数字员工）────────────────────── */}
        <section className={styles.section}>
          <header className={styles.sectionHead}>
            <div className={styles.sectionTitleGroup}>
              <span className={styles.sectionRule} aria-hidden="true" />
              <h2 className={styles.sectionTitle}>
                {t("employee.tab.agents")}
              </h2>
              <span className={styles.sectionCount}>{agentRows.length}</span>
            </div>
            <span
              className={styles.sectionLink}
              {...pressable(() => navigate("/agents?tab=agents"))}
            >
              {t("workbench.viewAllEmployees")}
              <ArrowRight size={13} />
            </span>
          </header>

          <div className={styles.agentGrid}>
            {loading && employees.length === 0
              ? Array.from({ length: 4 }).map((_, index) => (
                  // 占位卡：保持网格节奏，不把"加载中"误读成"没有员工"
                  <div key={index} className={styles.agentCardSkeleton} />
                ))
              : agentRows.map((employee, index) =>
                  renderEmployeeCard(employee, index),
                )}

            {/* 创建卡：与员工卡同尺寸占位，保持网格节奏 */}
            <div
              className={`${styles.agentCard} ${styles.agentCardCreate} ${styles.rise}`}
              style={seqStyle(agentRows.length + 1)}
              {...pressable(() => navigate("/agents?tab=agents"))}
            >
              <span className={styles.agentCardCreateIcon}>
                <Plus size={18} />
              </span>
              <span className={styles.agentCardName}>{t("agent.create")}</span>
              <span className={styles.quickDesc}>
                {t("workbench.createHint")}
              </span>
            </div>
          </div>
        </section>

        {/* ── 专家团：一个都没有时整面不渲染，不留空壳 ──────────────── */}
        {teamRows.length > 0 ? (
          <section className={styles.section}>
            <header className={styles.sectionHead}>
              <div className={styles.sectionTitleGroup}>
                <span className={styles.sectionRule} aria-hidden="true" />
                <h2 className={styles.sectionTitle}>
                  {t("employee.tab.teams")}
                </h2>
                <span className={styles.sectionCount}>{teamRows.length}</span>
              </div>
              <span
                className={styles.sectionLink}
                {...pressable(() => navigate("/agents?tab=team"))}
              >
                {t("workbench.viewAllEmployees")}
                <ArrowRight size={13} />
              </span>
            </header>

            <div className={styles.agentGrid}>
              {teamRows.map((employee, index) =>
                renderEmployeeCard(employee, index),
              )}
            </div>
          </section>
        ) : null}

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
