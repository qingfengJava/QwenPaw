/**
 * Admin/Pending — 待办收件箱（P3：人工介入点统一聚合视图）。
 *
 * 聚合四类需要人处理的待办：熔断升级 run / 待澄清 run / 待审批演进
 * 提案 / 失败定时任务；每项给跳转链接直达处理界面。
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Empty } from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { StatCard, StatusPill } from "@/components/staffdeck";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  expertCapabilityApi,
  type PendingItem,
} from "../../api/modules/admin";

const KIND_META: Record<
  string,
  { label: string; tone: "red" | "amber" | "blue" | "green" }
> = {
  run_escalated: { label: "熔断升级", tone: "red" },
  run_confirm: { label: "待澄清", tone: "amber" },
  proposal_review: { label: "提案待审", tone: "blue" },
  task_failed: { label: "定时任务失败", tone: "red" },
};

export default function PendingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { message } = useAppMessage();
  const [items, setItems] = useState<PendingItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<string>("all");

  const load = useCallback(async () => {
    try {
      const res = await expertCapabilityApi.pendingItems();
      setItems(res.items ?? []);
      setCounts(res.counts ?? {});
    } catch (err) {
      message.error(String(err));
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible =
    filter === "all" ? items : items.filter((i) => i.kind === filter);

  return (
    <div className="sd-page">
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("staffdeck.pending.title", "待办收件箱")}
      />

      {/* 分类统计卡 */}
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <StatCard
          value={items.length}
          label={t("staffdeck.pending.all", "全部待办")}
          onClick={() => setFilter("all")}
        />
        {Object.entries(KIND_META).map(([kind, meta]) => (
          <StatCard
            key={kind}
            value={counts[kind] ?? 0}
            label={meta.label}
            tone={meta.tone === "red" ? "red" : meta.tone === "amber" ? "default" : "default"}
            onClick={() => setFilter(kind)}
          />
        ))}
      </div>

      {/* 待办列表 */}
      <div className="sd-card" style={{ marginTop: 24, padding: "20px 24px" }}>
        {visible.length === 0 ? (
          <Empty description={t("staffdeck.pending.empty", "太棒了，没有待办")} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {visible.map((item) => {
              const meta = KIND_META[item.kind] ?? {
                label: item.kind,
                tone: "gray" as const,
              };
              return (
                <div
                  key={`${item.kind}-${item.id}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    border: "0.5px solid var(--sd-line)",
                    borderRadius: "var(--sd-radius-lg)",
                  }}
                >
                  <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        color: "var(--sd-ink)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {item.title}
                    </div>
                    {item.detail ? (
                      <div
                        style={{
                          fontSize: 12,
                          color: "var(--sd-text-3)",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.detail}
                      </div>
                    ) : null}
                  </div>
                  <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                    {(item.at || "").slice(0, 16).replace("T", " ")}
                  </span>
                  {item.link ? (
                    <Button size="small" onClick={() => navigate(item.link!)}>
                      {t("staffdeck.pending.handle", "去处理")}
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
