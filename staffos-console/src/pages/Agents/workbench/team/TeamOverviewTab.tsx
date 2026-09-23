/**
 * TeamOverviewTab — 专家团概览（工作台团队详情页首页 Tab）。
 *
 * 组织视角画像页：Hero 画像头（状态/模式徽标 + 简介 + 前往配置）→
 * 统计小卡行（成员数/总运行/成功/失败）→ 层级组织架构图 → 协作
 * 机制卡（模式说明来自 metadata，编排意图来自 plan_note）→ 团队
 * 建设区（任务模板 chips 点击即发起 test-run、使用案例、版本快照）。
 *
 * 单一数据来源：所有文案与枚举来自后端（metadata/记录字段），
 * 前端不硬编码模式语义；运行统计由最近一次 listRuns 拉取结果在
 * 渲染期内存聚合（一次查询，禁止逐条统计）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Spin, Table, Tag, Tooltip } from "antd";
import { ArrowUpCircle, RefreshCw, Settings2, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StatCard, StatusPill } from "@/components/staffdeck";
import { addRouterBasename } from "@/utils/navigationMode";
import { adminWorkforceApi } from "../../../../api/modules/admin/workforce";
import type { AdminTeamRun } from "../../../../api/modules/admin/workforce";
import type {
  ExpertTeamRecord,
  MemberUpdateItem,
  TeamCapabilityMember,
  TeamMetadata,
  TeamVersionRow,
} from "../../../../api/modules/admin";
import type { SectionStatus } from "./useTeamDetail";
import TeamOrgChart from "./TeamOrgChart";
import styles from "./teamDetail.module.less";

/** 活跃运行状态集合（统计卡"进行中"口径，与状态机值对齐）。 */
const ACTIVE_RUN_STATUSES = new Set([
  "planning",
  "awaiting_confirm",
  "running",
  "verifying",
  "repairing",
  "aggregating",
]);

/** 拉取的最近运行条数（内存聚合样本上限）。 */
const RUN_SAMPLE_LIMIT = 50;

export interface TeamOverviewTabProps {
  team: ExpertTeamRecord;
  members: TeamCapabilityMember[];
  versions: TeamVersionRow[];
  metadata: TeamMetadata | null;
  /** 成员升级提醒（可空；失败不阻塞页面）。 */
  memberUpdates: MemberUpdateItem[];
  teamId: string;
  canManage: boolean;
  /** 分区状态：能力投影/版本/升级提醒各自独立。 */
  capabilitiesStatus: SectionStatus;
  capabilitiesError: string;
  versionsStatus: SectionStatus;
  versionsError: string;
  /** 查看运行详情回调（父级设置 runId + 切换 Tab）。 */
  onViewRun?: (runId: string) => void;
  /** AI 变更确认或兜底轮询后手动刷新。 */
  onRefresh?: () => void;
}

export default function TeamOverviewTab({
  team,
  members,
  versions,
  metadata,
  memberUpdates,
  teamId,
  canManage,
  capabilitiesStatus,
  capabilitiesError,
  versionsStatus,
  versionsError,
  onViewRun,
  onRefresh,
}: TeamOverviewTabProps) {
  const { t } = useTranslation();

  // ── 运行统计：最近 50 条 run 一次拉取、渲染期内存聚合 ──
  const [runs, setRuns] = useState<AdminTeamRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState(false);
  useEffect(() => {
    let alive = true;
    setRunsLoading(true);
    setRunsError(false);
    adminWorkforceApi
      .listRuns({ team_id: teamId, limit: RUN_SAMPLE_LIMIT })
      .then((rows) => {
        if (alive) {
          setRuns(rows);
        }
      })
      .catch(() => {
        // 运行统计失败不阻塞画像页，但明确标记为加载失败。
        if (alive) {
          setRuns([]);
          setRunsError(true);
        }
      })
      .finally(() => {
        if (alive) {
          setRunsLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [teamId]);

  const runStats = useMemo(() => {
    let done = 0;
    let failed = 0;
    let active = 0;
    for (const run of runs) {
      if (run.status === "done") {
        done += 1;
      } else if (run.status === "failed" || run.status === "canceled") {
        failed += 1;
      } else if (ACTIVE_RUN_STATUSES.has(run.status)) {
        active += 1;
      }
    }
    return { total: runs.length, done, failed, active };
  }, [runs]);

  // ── 协作模式说明：唯一来源是 metadata.team_modes.description ──
  const modeInfo = metadata?.team_modes.find((m) => m.value === team.mode);
  const planNote =
    typeof team.orchestration?.plan_note === "string"
      ? (team.orchestration.plan_note as string)
      : "";
  // 有效配置：runtime_enabled 缺省 true（后端统一提供，前端不硬编码）
  const defaultRuntime = metadata?.default_runtime_enabled ?? true;
  const runtimeEnabled =
    typeof team.orchestration?.runtime_enabled === "boolean"
      ? team.orchestration.runtime_enabled
      : defaultRuntime;

  // ── 升级提醒：可升级成员列表 ──
  const upgradableMembers = useMemo(
    () => memberUpdates.filter((m) => m.upgradable),
    [memberUpdates],
  );

  // ── 任务模板：点击即发起一次团队试运行（运维侧可观测） ──
  const [launching, setLaunching] = useState<string | null>(null);
  // 执行回执：成功时记录 run_id 用于跳转，失败时记录错误信息。
  const [launchResult, setLaunchResult] = useState<
    { type: "success"; runId: string; prompt: string } |
    { type: "error"; message: string; prompt: string } |
    null
  >(null);
  const sampleTasks = team.sample_tasks ?? [];
  const showcase = team.showcase ?? [];

  const launchSampleTask = useCallback(
    async (prompt: string) => {
      setLaunching(prompt);
      setLaunchResult(null);
      try {
        const run = await adminWorkforceApi.testRun(teamId, prompt);
        setLaunchResult({ type: "success", runId: run.id, prompt });
      } catch (err) {
        setLaunchResult({ type: "error", message: String(err), prompt });
      } finally {
        setLaunching(null);
      }
    },
    [teamId],
  );

  const goToConfig = () => {
    window.location.assign(
      addRouterBasename(window.location.pathname, `/agents/teams/${teamId}`),
    );
  };

  const statusTone =
    team.status === "published" ? "green" : team.status === "archived" ? "gray" : "blue";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ── Hero 画像头 ── */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.heroHead}>
          <div
            className={styles.heroAvatar}
            style={{ background: "linear-gradient(135deg, #14b8a6, #0ea5e9)" }}
          >
            <Users size={26} />
          </div>
          <div className={styles.heroTitleWrap}>
            <div className={styles.heroTitleRow}>
              <span className={styles.heroName}>{team.name}</span>
              <StatusPill tone={statusTone}>
                {team.status === "published"
                  ? t("workbench.team.statusPublished", "已发布")
                  : team.status === "archived"
                    ? t("workbench.team.statusArchived", "已归档")
                    : t("workbench.team.statusDraft", "草稿")}
              </StatusPill>
              <Tag color={team.mode === "pipeline" ? "blue" : "purple"}>
                {modeInfo?.label || team.mode}
              </Tag>
              <StatusPill tone={team.version > 1 ? "green" : "blue"}>
                {t("workbench.team.versionN", "v{{v}}", { v: team.version })}
              </StatusPill>
            </div>
            <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
              {t("workbench.team.memberCount", "{{n}} 位成员", {
                n: members.length,
              })}
            </span>
          </div>
          {canManage ? (
            <span style={{ marginLeft: "auto", flex: "0 0 auto", display: "flex", gap: 8 }}>
              {onRefresh && (
                <Tooltip title={t("workbench.team.refresh", "刷新")}>
                  <Button
                    icon={<RefreshCw size={14} />}
                    onClick={onRefresh}
                    aria-label={t("workbench.team.refresh", "刷新")}
                  />
                </Tooltip>
              )}
              <Button icon={<Settings2 size={14} />} onClick={goToConfig}>
                {t("workbench.team.goConfig", "前往配置")}
              </Button>
            </span>
          ) : null}
        </div>
        {team.description ? (
          <p className={styles.heroDesc}>{team.description}</p>
        ) : null}
      </div>

      {/* ── 统计小卡行 ── */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <StatCard
          value={members.length}
          label={t("workbench.team.statMembers", "团队成员")}
        />
        <StatCard
          value={runsLoading ? "…" : runStats.total}
          label={t("workbench.team.statTotalRuns", "最近可见运行")}
        />
        <StatCard
          value={runsLoading ? "…" : runStats.done}
          label={t("workbench.team.statDone", "成功交付")}
          tone="green"
        />
        <StatCard
          value={runsLoading ? "…" : runStats.failed}
          label={t("workbench.team.statFailed", "失败/取消")}
          tone="red"
        />
      </div>
      {runsError ? (
        <Alert
          type="warning"
          showIcon
          message={t(
            "workbench.team.runsLoadError",
            "运行统计加载失败，上方数据可能不准确",
          )}
          style={{ marginBottom: 4 }}
        />
      ) : null}

      {/* ── 成员升级提醒 ── */}
      {upgradableMembers.length > 0 ? (
        <Alert
          type="info"
          showIcon
          icon={<ArrowUpCircle size={16} />}
          message={t(
            "workbench.team.upgradeAvailable",
            "{{n}} 位成员有新版本可升级",
            { n: upgradableMembers.length },
          )}
          description={
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {upgradableMembers.map((m) => (
                <li key={m.expert_id}>
                  {m.expert_name || m.expert_id}
                  {" — v"}{m.bound_version ?? "—"}{" → v"}{m.latest_version}
                </li>
              ))}
            </ul>
          }
          style={{ marginBottom: 4 }}
        />
      ) : null}

      {/* ── 层级组织架构 ── */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.sectionTitle}>
          {t("workbench.team.orgTitle", "团队组织")}
          {capabilitiesStatus === "loading" ? <Spin size="small" style={{ marginLeft: 8 }} /> : null}
        </div>
        {capabilitiesStatus === "error" ? (
          <Alert type="warning" showIcon message={capabilitiesError || t("workbench.team.capabilitiesLoadError", "能力投影加载失败，组织图可能不完整")} />
        ) : (
          <TeamOrgChart members={members} />
        )}
      </div>

      {/* ── 协作机制 ── */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.sectionTitle}>
          {t("workbench.team.collabTitle", "协作机制")}
          <Tag color={runtimeEnabled ? "geekblue" : "default"}>
            {runtimeEnabled
              ? t("workbench.team.orchOn", "运行时编排")
              : t("workbench.team.orchOff", "基础模式")}
          </Tag>
        </div>
        <p className={styles.heroDesc} style={{ marginTop: 10 }}>
          {modeInfo?.description ||
            t("workbench.team.collabEmpty", "该模式暂无说明，请联系管理员补充。")}
        </p>
        {planNote ? (
          <p className={styles.heroDesc} style={{ marginTop: 8 }}>
            {t("workbench.team.planNote", "编排意图")}：{planNote}
          </p>
        ) : null}
      </div>

      {/* ── 团队建设：任务模板 / 使用案例 / 版本快照 ── */}
      <div className="sd-card" style={{ padding: "20px 24px" }}>
        <div className={styles.sectionTitle}>
          {t("workbench.team.buildingTitle", "团队建设")}
        </div>

        {sampleTasks.length > 0 ? (
          <>
            <div className={styles.taskChipRow}>
              {sampleTasks.map((task) => (
                <Tooltip
                  key={task.title}
                  title={t("workbench.team.taskLaunchHint", "点击以该任务发起一次团队运行")}
                >
                  <button
                    type="button"
                    className={styles.taskChip}
                    disabled={launching !== null}
                    onClick={() => void launchSampleTask(task.prompt)}
                  >
                    {task.title}
                    {launching === task.prompt
                      ? t("workbench.team.taskLaunching", "（发起中…）")
                      : ""}
                  </button>
                </Tooltip>
              ))}
            </div>
            {launchResult ? (
              launchResult.type === "success" ? (
                <Alert
                  type="success"
                  showIcon
                  style={{ marginTop: 8 }}
                  message={t(
                    "workbench.team.taskLaunchOk",
                    "已发起试运行",
                  )}
                  description={
                    <span>
                      {launchResult.prompt}
                      {" — "}
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0, height: "auto" }}
                        onClick={() => {
                          // 通过父级回调跳转到运行日志详情
                          onViewRun?.(launchResult.runId);
                        }}
                      >
                        {t("workbench.team.taskViewRun", "查看运行")}
                      </Button>
                    </span>
                  }
                  closable
                  onClose={() => setLaunchResult(null)}
                />
              ) : (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginTop: 8 }}
                  message={t(
                    "workbench.team.taskLaunchFail",
                    "试运行发起失败",
                  )}
                  description={launchResult.message}
                  closable
                  onClose={() => setLaunchResult(null)}
                />
              )
            ) : null}
          </>
        ) : null}

        {showcase.length > 0 ? (
          <div className={styles.caseList}>
            {showcase.map((item) => (
              <div key={item.title} className={styles.caseRow}>
                <span className={styles.caseTitle}>{item.title}</span>
                {item.desc ? (
                  <span className={styles.caseDesc}>{item.desc}</span>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {sampleTasks.length === 0 && showcase.length === 0 ? (
          <div style={{ marginTop: 12 }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                "workbench.team.buildingEmpty",
                "暂无任务模板与使用案例（管理员可在配置工作台维护）",
              )}
            />
          </div>
        ) : null}

        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, color: "var(--sd-text-2)", marginBottom: 8 }}>
            {t("workbench.team.versionsTitle", "版本快照")}
            {versionsStatus === "loading" ? <Spin size="small" style={{ marginLeft: 8 }} /> : null}
          </div>
          {versionsStatus === "error" ? (
            <Alert type="warning" showIcon message={versionsError || t("workbench.team.versionsLoadError", "版本记录加载失败")} />
          ) : (
            <Table<TeamVersionRow>
              rowKey="version"
              size="small"
              dataSource={versions}
              pagination={false}
              locale={{
                emptyText: t("workbench.team.noVersions", "尚未发布过版本"),
              }}
              columns={[
                { title: "v", dataIndex: "version", width: 80 },
                {
                  title: t("workbench.team.publishedBy", "发布人"),
                  dataIndex: "published_by",
                },
                {
                  title: t("workbench.team.publishedAt", "发布时间"),
                  dataIndex: "published_at",
                  render: (v: string | null) =>
                    v ? new Date(v).toLocaleString("zh-CN") : "—",
                },
              ]}
            />
          )}
        </div>
      </div>
    </div>
  );
}
