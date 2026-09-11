/**
 * AgentOverviewTab.tsx — 员工概览（工作台 / 详情页的档案中心首页）。
 *
 * 结构（对标 Coze 编辑器档案页）：
 *   Hero 档案头（DiceBear 形象 / 渐变首字符 + 名称 + 运行状态 + 简介，
 *   详情页左栏已有头像时可通过 showHeader=false 关闭）→
 *   统计卡行（4 × StatCard，数据来自 /agent-stats/summary-brief）→
 *   基础配置文档区（真实读取智能体工作区根的 PROFILE.md / AGENTS.md /
 *   SOUL.md / agent.json，文件 chip 切换；Markdown 渲染，agent.json 以
 *   格式化 JSON 展示）→ 快捷指令 chips。近期活动已拆到独立的
 *   AgentActivityTab（「动态」Tab）。
 *
 * 诚实数据原则：后端未就绪的指标（好评率）一律显示占位，不造假。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Pin, Sparkles } from "lucide-react";
import { StatCard, StatusPill } from "@/components/staffdeck";
import ExpertAvatar from "@/components/ExpertAvatar";
import { avatarGradient } from "@/utils/avatarGradient";
import { workspaceApi } from "@/api/modules/workspace";
import { providerApi } from "@/api/modules/provider";
import { isExpertAgentId } from "@/api/modules/xianFeedback";
import ModelSelector from "@/pages/Chat/ModelSelector";
import { useExpertIcons } from "@/hooks/useExpertIcons";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import type { AgentSummary } from "@/api/types/agents";
import { useBriefStats } from "./useBriefStats";
import { IDENTITY_DOC_FILES } from "./identityDocFiles";
import { AGENT_DOCS_CHANGED_EVENT } from "../Chat/agentDocsSync";
import styles from "./detail.module.less";

/**
 * 基础配置文件清单（工作区根路径）。按展示优先级排序，逐个探测，
 * 不存在的自动从 chip 列表消失。清单与对话修改闭环共用（见
 * identityDocFiles.ts），避免展示/预填/回填三处定义漂移。
 */
const CONFIG_FILES = IDENTITY_DOC_FILES;

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
  /**
   * 是否渲染 Hero 档案头。旧详情页左栏（EmployeeProfileAside）已有
   * 头像卡，传 false 避免重复；工作台右栏无侧栏，保持默认 true。
   */
  showHeader?: boolean;
  /** 发起 AI 调优（跳对话 Tab 并预填指令）。 */
  onAiTune: (prompt: string) => void;
}

export default function AgentOverviewTab({
  agent,
  aid,
  showHeader = true,
  onAiTune,
}: AgentOverviewTabProps) {
  const { t } = useTranslation();
  const { stats, loading } = useBriefStats(aid);

  // ── Hero 档案头：数字员工形象解析规则与左栏档案卡同源 ──
  const expertId = isExpertAgentId(aid);
  const expertIcon = useExpertIcons()[expertId];
  const displayName = agent ? getAgentDisplayName(agent, t) : aid;

  // ── 默认模型跟随态：员工未单独配置（scope=agent 无 active_llm）时
  // 显示「跟随全局默认」徽标；ModelSelector 保存成功后派发
  // model-switched 事件，借它静默刷新本态。
  const [followingGlobal, setFollowingGlobal] = useState(false);
  const refreshFollowing = useCallback(async () => {
    try {
      const active = await providerApi.getActiveModels({
        scope: "agent",
        agent_id: aid,
      });
      setFollowingGlobal(!active.active_llm);
    } catch {
      setFollowingGlobal(false);
    }
  }, [aid]);
  useEffect(() => {
    void refreshFollowing();
    window.addEventListener("model-switched", refreshFollowing);
    return () => window.removeEventListener("model-switched", refreshFollowing);
  }, [refreshFollowing]);

  // ── 基础配置：并发探测工作区根的配置文件，取到内容的进入 chip 列表 ──
  const [configDocs, setConfigDocs] = useState<Record<string, string>>({});
  const [configsLoading, setConfigsLoading] = useState(true);
  const [activeConfig, setActiveConfig] = useState<string | null>(null);

  // 并发探测白名单档案文件，取到内容的进入 chip 列表（供挂载与
  // 对话修改刷新共用；root="workspace"：智能体自身存储根，跟随
  // selectedAgent 借壳，工作台调试模式下自动指向草稿工作区）。
  const fetchConfigDocs = useCallback(async () => {
    const results = await Promise.allSettled(
      CONFIG_FILES.map(async (name) => ({
        name,
        content: (
          await workspaceApi.loadFileText(name, undefined, "workspace")
        ).content,
      })),
    );
    const docs: Record<string, string> = {};
    results.forEach((result) => {
      if (result.status === "fulfilled" && result.value.content.trim()) {
        docs[result.value.name] = result.value.content;
      }
    });
    return docs;
  }, []);

  useEffect(() => {
    let alive = true;
    setConfigsLoading(true);
    setConfigDocs({});
    setActiveConfig(null);
    void fetchConfigDocs().then((docs) => {
      if (!alive) return;
      setConfigDocs(docs);
      setConfigsLoading(false);
      setActiveConfig(Object.keys(docs)[0] ?? null);
    });
    return () => {
      alive = false;
    };
  }, [aid, fetchConfigDocs]);

  // 对话修改闭环：聊天流结束（本轮引用了档案文件）后广播的变更事件
  // → 静默重拉档案内容；保持当前选中文件，消失时回退到第一个。
  useEffect(() => {
    const handleDocsChanged = () => {
      void fetchConfigDocs().then((docs) => {
        setConfigDocs(docs);
        setConfigsLoading(false);
        setActiveConfig((prev) =>
          prev && docs[prev] !== undefined
            ? prev
            : (Object.keys(docs)[0] ?? null),
        );
      });
    };
    window.addEventListener(AGENT_DOCS_CHANGED_EVENT, handleDocsChanged);
    return () =>
      window.removeEventListener(AGENT_DOCS_CHANGED_EVENT, handleDocsChanged);
  }, [fetchConfigDocs]);

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

  const activeContent = activeConfig ? configDocs[activeConfig] : undefined;

  return (
    <div className={styles.overviewWrap}>
      {/* Hero 档案头（工作台右栏；详情页左栏已有头像时关闭） */}
      {showHeader && (
        <div className={`${styles.heroCard} sd-card`}>
          {expertId ? (
            <ExpertAvatar
              icon={expertIcon}
              expertId={expertId}
              name={displayName}
              size={56}
              className={styles.heroAvatar}
            />
          ) : (
            <div
              className={styles.heroAvatar}
              style={{ background: avatarGradient(aid + displayName) }}
            >
              {(displayName || "?").slice(0, 1)}
            </div>
          )}
          <div className={styles.heroInfo}>
            <div className={styles.heroNameRow}>
              <span className={styles.heroName} title={displayName}>
                {displayName}
              </span>
              {(agent?.id === "default" || agent?.pinned) && (
                <Pin size={13} className={styles.heroPin} />
              )}
              <StatusPill tone={agent?.enabled ? "green" : "gray"}>
                {agent?.enabled
                  ? t("agent.status.running", "Running")
                  : t("agent.status.disabled", "Disabled")}
              </StatusPill>
            </div>
            <p className={styles.heroDesc}>
              {agent?.description || "\u00a0"}
            </p>
            {/* 默认模型：复用聊天页 ModelSelector（selectedAgent 由布局同步），
                写入即该员工后台默认运行模型（前台未指定时使用） */}
            <div className={styles.modelSelectorRow}>
              <span className={styles.modelSelectorLabel}>
                {t("agentDetail.model", "模型")}
              </span>
              <ModelSelector />
              {followingGlobal && (
                <span
                  className={styles.modelFollowTag}
                  title={t(
                    "agentDetail.modelFollowGlobalTitle",
                    "未单独配置模型，当前跟随全局默认；选择模型即设为本员工专属默认",
                  )}
                >
                  {t("agentDetail.modelFollowGlobal", "跟随全局默认")}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

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

      {/* 基础配置文档区：智能体自己的 PROFILE.md / AGENTS.md / rules 等 */}
      <section className={styles.overviewSection}>
        <h3 className={styles.sectionTitle}>
          {t("agentDetail.baseConfig", "Base Configuration")}
        </h3>
        <div className={`${styles.profileDocCard} sd-card`}>
          {/* 文件 chip 切换 + 对话修改入口（锚定当前激活文件） */}
          {Object.keys(configDocs).length > 0 && (
            <div className={styles.configFileRow}>
              {Object.keys(configDocs).map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`${styles.configChip}${
                    name === activeConfig ? ` ${styles.configChipActive}` : ""
                  }`}
                  onClick={() => setActiveConfig(name)}
                >
                  {name}
                </button>
              ))}
              {activeConfig && (
                <button
                  type="button"
                  className={`${styles.configChip} ${styles.docEditChip}`}
                  title={t("agentDetail.docEditChatTitle", "针对当前文件发起对话修改", {
                    file: activeConfig,
                  })}
                  onClick={() =>
                    onAiTune(
                      t(
                        "agentDetail.docEditPrompt",
                        "帮我编辑 @ {{file}}，在开始前请先向我确认具体需要修改的内容",
                        { file: activeConfig },
                      ),
                    )
                  }
                >
                  <Sparkles size={12} />
                  {t("agentDetail.docEditChat", "对话修改")}
                </button>
              )}
            </div>
          )}

          {/* 内容区：Markdown 渲染 / agent.json 格式化 JSON */}
          {configsLoading ? (
            <p className={styles.docBody}>
              {t("agentDetail.baseConfigLoading", "Loading…")}
            </p>
          ) : activeContent ? (
            activeConfig?.endsWith(".json") ? (
              <pre className={styles.configJson}>
                {formatJsonSafely(activeContent)}
              </pre>
            ) : (
              <div className={styles.mdBody}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {stripFrontmatter(activeContent)}
                </ReactMarkdown>
              </div>
            )
          ) : (
            <p className={styles.docBody}>
              {t(
                "agentDetail.baseConfigEmpty",
                "No configuration files in the workspace yet.",
              )}
            </p>
          )}

          {/* 快捷指令（AI 调优入口） */}
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
    </div>
  );
}

/** agent.json 容错格式化：解析失败时原样返回。 */
function formatJsonSafely(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

/** 剥离 Markdown 头部 YAML frontmatter（--- 包裹的元数据块），避免渲染成正文。 */
function stripFrontmatter(md: string): string {
  const match = /^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/.exec(md);
  return match ? md.slice(match[0].length) : md;
}
