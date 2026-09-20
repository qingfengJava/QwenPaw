/**
 * Admin/Attribution — 归因桶差评热力分析（缺口③消费面）。
 *
 * 跨专家视角：13 归因桶 × 日期的热力矩阵（GitHub contribution 风格，
 * 五档色阶走 staffdeck tokens）+ 桶总量排行 + 员工归因 top5；点击桶行
 * 下抽查看关联演进提案（差评 → 归因 → 演进闭环的运营消费入口）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Drawer, Empty, Segmented, Table } from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/staffdeck";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  attributionApi,
  evolutionApi,
  type AttributionHeatmap,
  type EvolutionProposal,
} from "../../api/modules/admin";
import styles from "./attribution.module.less";

/** 13 桶中文释义（与后端 ATTRIBUTION_BUCKETS 一一对应；统计维度展示名）。 */
const BUCKET_LABELS: Record<string, string> = {
  model_issue: "模型能力不足",
  skill_instruction_issue: "技能指令缺陷",
  sop_trigger_issue: "SOP 触发/识别偏差",
  sop_slot_issue: "SOP 槽位/信息收集缺陷",
  sop_transition_issue: "SOP 步骤流转缺陷",
  sop_capability_issue: "SOP 能力引用缺失",
  knowledge_gap: "知识缺口",
  tool_or_runtime_issue: "工具/运行时故障",
  user_random_or_unclear: "用户输入随机/不清晰",
  positive_or_resolved: "实为正面或已解决",
  needs_model_analysis: "需更强模型分析",
  unknown: "无法归因",
};

/** 五档色阶（值 → 底色；走 staffdeck 状态色板）。 */
function heatColor(count: number): string {
  if (count <= 0) return "transparent";
  if (count <= 2) return "rgba(210, 11, 11, 0.15)";
  if (count <= 5) return "rgba(210, 11, 11, 0.35)";
  if (count <= 9) return "rgba(210, 11, 11, 0.60)";
  return "rgba(210, 11, 11, 0.85)";
}

export default function AttributionPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AttributionHeatmap | null>(null);
  const [loading, setLoading] = useState(false);
  const [drawerBucket, setDrawerBucket] = useState<string>("");
  const [drawerProposals, setDrawerProposals] = useState<EvolutionProposal[]>(
    [],
  );
  const [drawerLoading, setDrawerLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await attributionApi.heatmap(days));
    } catch (err) {
      message.error(String(err));
    } finally {
      setLoading(false);
    }
  }, [days, message]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 最热桶（totals 最大且 >0）。 */
  const hottestBucket = useMemo(() => {
    if (!data) return "";
    let best = "";
    let bestCount = 0;
    for (const [bucket, count] of Object.entries(data.totals)) {
      if (count > bestCount) {
        best = bucket;
        bestCount = count;
      }
    }
    return best;
  }, [data]);

  const openBucketDrawer = useCallback(
    async (bucket: string) => {
      setDrawerBucket(bucket);
      setDrawerLoading(true);
      try {
        const res = await evolutionApi.list("", "");
        const all = res.proposals ?? [];
        setDrawerProposals(
          all.filter((p) => {
            const candidate = p.candidate as Record<string, unknown> | null;
            return (candidate?.bucket ?? "unknown") === bucket;
          }),
        );
      } catch (err) {
        message.error(String(err));
        setDrawerProposals([]);
      } finally {
        setDrawerLoading(false);
      }
    },
    [message],
  );

  // 日期列压缩显示：仅每月 1 号与每隔 7 天展示标签
  const dateLabel = (date: string, index: number) => {
    if (date.endsWith("-01") || index % 7 === 0) return date.slice(5);
    return "";
  };

  /** 最热桶展示名（不含计数，计数由徽章单独呈现）；无数据时为空串。 */
  const hottestName = hottestBucket
    ? (BUCKET_LABELS[hottestBucket] ?? hottestBucket)
    : "";
  const hottestCount = hottestBucket ? (data?.totals[hottestBucket] ?? 0) : 0;

  return (
    <div className="sd-page">
      <PageHeader
        current={t(
          "staffdeck.attribution.title",
          "差评归因分析"
        )}
      />

      {/* 统计区：区块 header 行（左标题 + 右时间窗）+ 三列等高 KPI 卡网格 */}
      <section className={styles.statsSection}>
        <div className={styles.statsHeader}>
          <span className={styles.statsTitle}>
            {t("staffdeck.attribution.overview", "概览")}
          </span>
          <Segmented
            value={days}
            onChange={(v) => setDays(Number(v))}
            options={[
              { label: "7 天", value: 7 },
              { label: "30 天", value: 30 },
              { label: "90 天", value: 90 },
            ]}
          />
        </div>
        <div className={styles.kpiGrid}>
          <div className={styles.kpiCard}>
            <div className={styles.kpiValue}>{data?.total ?? 0}</div>
            <div className={styles.kpiLabel}>
              {t("staffdeck.attribution.total", "归因提案总数")}
            </div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiBucketRow}>
              {hottestName ? (
                <>
                  <span className={styles.kpiBucketName} title={hottestName}>
                    {hottestName}
                  </span>
                  <span className="sd-pill sd-pill-gray sd-pill-nodot">
                    {hottestCount}
                  </span>
                </>
              ) : (
                <span
                  className={`${styles.kpiBucketName} ${styles.kpiBucketNameEmpty}`}
                >
                  —
                </span>
              )}
            </div>
            <div className={styles.kpiLabel}>
              {t("staffdeck.attribution.hottest", "最热归因桶")}
            </div>
          </div>
          <div className={styles.kpiCard}>
            <div className={styles.kpiValue}>
              {data?.top_experts?.length ?? 0}
            </div>
            <div className={styles.kpiLabel}>
              {t("staffdeck.attribution.expertsCovered", "涉及员工数")}
            </div>
          </div>
        </div>
      </section>

      {/* 热力矩阵 */}
      <div
        className="sd-card"
        style={{ marginTop: 24, padding: "20px 24px" }}
      >
        <div
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: "var(--sd-ink)",
            marginBottom: 16,
          }}
        >
          {t("staffdeck.attribution.matrix", "桶 × 日期热力矩阵")}
        </div>
        {loading || !data ? (
          <Empty description={t("staffdeck.attribution.loading", "加载中…")} />
        ) : data.total === 0 ? (
          <Empty
            description={t(
              "staffdeck.attribution.empty",
              "窗口内暂无归因提案（差评自省产出会出现在这里）"
            )}
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", minWidth: "100%" }}>
              <thead>
                <tr>
                  <th
                    style={{
                      textAlign: "left",
                      padding: "4px 12px 4px 0",
                      fontSize: 12,
                      color: "var(--sd-text-2)",
                      fontWeight: 500,
                      position: "sticky",
                      left: 0,
                      background: "var(--sd-card)",
                      minWidth: 168,
                    }}
                  />
                  {data.dates.map((date, i) => (
                    <th
                      key={date}
                      style={{
                        padding: "4px 1px",
                        fontSize: 10,
                        color: "var(--sd-text-3)",
                        fontWeight: 400,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {dateLabel(date, i)}
                    </th>
                  ))}
                  <th
                    style={{
                      padding: "4px 8px",
                      fontSize: 12,
                      color: "var(--sd-text-2)",
                      fontWeight: 500,
                    }}
                  >
                    {t("staffdeck.attribution.totalCol", "合计")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.buckets.map((bucket) => {
                  const rowTotal = data.totals[bucket] ?? 0;
                  return (
                    <tr
                      key={bucket}
                      onClick={() => void openBucketDrawer(bucket)}
                      style={{ cursor: "pointer" }}
                    >
                      <td
                        style={{
                          padding: "3px 12px 3px 0",
                          fontSize: 12,
                          color: "var(--sd-ink)",
                          position: "sticky",
                          left: 0,
                          background: "var(--sd-card)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {BUCKET_LABELS[bucket] ?? bucket}
                      </td>
                      {data.dates.map((date) => {
                        const count = data.matrix[bucket]?.[date] ?? 0;
                        return (
                          <td key={date} style={{ padding: "1px" }}>
                            <div
                              title={`${BUCKET_LABELS[bucket] ?? bucket} ${date}: ${count}`}
                              style={{
                                width: 14,
                                height: 14,
                                borderRadius: 3,
                                background: heatColor(count),
                                border: "0.5px solid var(--sd-line)",
                              }}
                            />
                          </td>
                        );
                      })}
                      <td
                        style={{
                          padding: "3px 8px",
                          fontSize: 12,
                          fontWeight: 600,
                          color: rowTotal > 0 ? "var(--sd-ink)" : "var(--sd-text-3)",
                          textAlign: "center",
                        }}
                      >
                        {rowTotal}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 员工归因 top5 */}
      <div
        className="sd-card"
        style={{ marginTop: 24, padding: "20px 24px" }}
      >
        <div
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: "var(--sd-ink)",
            marginBottom: 16,
          }}
        >
          {t("staffdeck.attribution.topExperts", "员工归因排行（Top 5）")}
        </div>
        {!data || data.top_experts.length === 0 ? (
          <Empty description={t("staffdeck.attribution.noExperts", "暂无数据")} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {data.top_experts.map((row) => {
              const max = data.top_experts[0]?.count || 1;
              return (
                <div key={row.expert_id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span
                    style={{
                      width: 160,
                      fontSize: 13,
                      color: "var(--sd-ink)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {row.name}
                  </span>
                  <div
                    style={{
                      flex: 1,
                      height: 10,
                      borderRadius: 999,
                      background: "var(--sd-surface)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.max(4, (row.count / max) * 100)}%`,
                        height: "100%",
                        borderRadius: 999,
                        background: "var(--sd-amber, #d97706)",
                      }}
                    />
                  </div>
                  <span style={{ fontSize: 13, color: "var(--sd-text-2)", width: 40, textAlign: "right" }}>
                    {row.count}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 桶下钻：关联提案 */}
      <Drawer
        title={BUCKET_LABELS[drawerBucket] ?? drawerBucket}
        open={Boolean(drawerBucket)}
        onClose={() => setDrawerBucket("")}
        width={560}
      >
        {drawerLoading ? (
          <Empty description={t("staffdeck.attribution.loading", "加载中…")} />
        ) : drawerProposals.length === 0 ? (
          <Empty description={t("staffdeck.attribution.noProposals", "该桶暂无提案")} />
        ) : (
          <Table
            size="small"
            rowKey={(r) => r.id}
            dataSource={drawerProposals}
            pagination={{ pageSize: 10 }}
            columns={[
              {
                title: t("staffdeck.attribution.proposalTitle", "标题"),
                dataIndex: "title",
                ellipsis: true,
              },
              {
                title: t("staffdeck.attribution.proposalExpert", "员工"),
                dataIndex: "expert_id",
                width: 130,
                ellipsis: true,
              },
              {
                title: t("staffdeck.attribution.proposalStatus", "状态"),
                dataIndex: "status",
                width: 110,
                render: (status: string) => (
                  <StatusPill
                    tone={
                      status === "published"
                        ? "green"
                        : status === "rejected" || status === "rolled_back"
                          ? "red"
                          : status === "approved"
                            ? "blue"
                            : "gray"
                    }
                  >
                    {status}
                  </StatusPill>
                ),
              },
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
