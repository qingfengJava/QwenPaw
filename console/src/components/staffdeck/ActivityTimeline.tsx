/**
 * staffdeck/ActivityTimeline.tsx — Day/Week/Month 三态活动时间线
 * （StaffDeck WorkRecordTab 的 ActivityTimeline 简化移植）。
 *
 * - 数据：byDay（按天密度）+ timeline（事件列表）；
 * - Day：单日事件列表；Week：7 列密度条；Month：月历密度点；
 * - 点击密度格切换到该日 Day 视图。
 */
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TimelineEvent } from "@/api/modules/admin";
import { StatusPill } from "./StatusPill";

type Mode = "day" | "week" | "month";

function fmt(d: Date): string {
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const WEEKDAY_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

export function ActivityTimeline({
  byDay,
  timeline,
}: {
  byDay: Array<{ date: string; tasks: number; feedback: number }>;
  timeline: TimelineEvent[];
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("week");
  const [anchor, setAnchor] = useState<Date>(new Date());

  const density = useMemo(() => {
    const map = new Map<string, number>();
    byDay.forEach((d) => map.set(d.date, (d.tasks || 0) + (d.feedback || 0)));
    return map;
  }, [byDay]);

  const dayEvents = useMemo(() => {
    const key = fmt(anchor);
    return timeline.filter((e) => (e.at || "").slice(0, 10) === key);
  }, [timeline, anchor]);

  const weekStart = useMemo(() => {
    const d = new Date(anchor);
    const dow = (d.getDay() + 6) % 7; // 周一为一周开始
    d.setDate(d.getDate() - dow);
    return d;
  }, [anchor]);

  const monthGrid = useMemo(() => {
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const start = new Date(first);
    start.setDate(start.getDate() - ((first.getDay() + 6) % 7));
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [anchor]);

  const rangeLabel = useMemo(() => {
    if (mode === "day") return fmt(anchor);
    if (mode === "week") {
      const end = new Date(weekStart);
      end.setDate(end.getDate() + 6);
      return `${fmt(weekStart)} ~ ${fmt(end)}`;
    }
    return `${anchor.getFullYear()} 年 ${anchor.getMonth() + 1} 月`;
  }, [mode, anchor, weekStart]);

  const shift = (dir: 1 | -1) => {
    const next = new Date(anchor);
    if (mode === "day") next.setDate(next.getDate() + dir);
    else if (mode === "week") next.setDate(next.getDate() + dir * 7);
    else next.setMonth(next.getMonth() + dir);
    setAnchor(next);
  };

  const densityColor = (n: number) => {
    if (!n) return "var(--sd-gray-bg)";
    if (n <= 2) return "var(--sd-blue-bg)";
    if (n <= 5) return "#c9dcff";
    return "var(--sd-link)";
  };

  const cellBase: React.CSSProperties = {
    borderRadius: 8,
    minHeight: 44,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    border: "0.5px solid var(--sd-line)",
  };

  return (
    <div className="sd-card" style={{ padding: "20px 24px" }}>
      {/* 工具行：模式切换 + 日期导航 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ fontSize: 14, color: "var(--sd-ink)", fontWeight: 600 }}>
          {rangeLabel}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", gap: 4 }}>
            {(["day", "week", "month"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                style={{
                  border: "none",
                  cursor: "pointer",
                  fontSize: 13,
                  padding: "4px 12px",
                  borderRadius: "var(--sd-radius-pill)",
                  background:
                    mode === m ? "var(--sd-ink)" : "var(--sd-gray-bg)",
                  color: mode === m ? "#fff" : "var(--sd-text-2)",
                }}
              >
                {t(`staffdeck.timeline.${m}`, m.toUpperCase())}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => shift(-1)} style={navBtnStyle}>
            ‹
          </button>
          <button
            type="button"
            onClick={() => setAnchor(new Date())}
            style={navBtnStyle}
          >
            {t("staffdeck.timeline.today", "今天")}
          </button>
          <button type="button" onClick={() => shift(1)} style={navBtnStyle}>
            ›
          </button>
        </div>
      </div>

      {/* 主体 */}
      <div style={{ marginTop: 18 }}>
        {mode === "week" ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 8 }}>
            {weekStart &&
              Array.from({ length: 7 }, (_, i) => {
                const d = new Date(weekStart);
                d.setDate(d.getDate() + i);
                const key = fmt(d);
                const n = density.get(key) || 0;
                return (
                  <div key={key}>
                    <div
                      style={{
                        textAlign: "center",
                        fontSize: 12,
                        color: "var(--sd-text-3)",
                        marginBottom: 6,
                      }}
                    >
                      {WEEKDAY_LABELS[i]}
                    </div>
                    <div
                      style={{
                        ...cellBase,
                        background: densityColor(n),
                        color: n > 5 ? "#fff" : "var(--sd-text-2)",
                        outline:
                          key === fmt(new Date())
                            ? "2px solid var(--sd-link)"
                            : undefined,
                      }}
                      onClick={() => {
                        setAnchor(d);
                        setMode("day");
                      }}
                    >
                      <div style={{ fontSize: 16, fontWeight: 600 }}>
                        {d.getDate()}
                      </div>
                      <div style={{ fontSize: 11 }}>{n || ""}</div>
                    </div>
                  </div>
                );
              })}
          </div>
        ) : null}

        {mode === "month" ? (
          <div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(7, 1fr)",
                gap: 6,
                marginBottom: 6,
              }}
            >
              {WEEKDAY_LABELS.map((w) => (
                <div
                  key={w}
                  style={{
                    textAlign: "center",
                    fontSize: 12,
                    color: "var(--sd-text-3)",
                  }}
                >
                  {w}
                </div>
              ))}
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(7, 1fr)",
                gap: 6,
              }}
            >
              {monthGrid.map((d) => {
                const key = fmt(d);
                const inMonth = d.getMonth() === anchor.getMonth();
                const n = density.get(key) || 0;
                return (
                  <div
                    key={key}
                    style={{
                      ...cellBase,
                      minHeight: 40,
                      opacity: inMonth ? 1 : 0.35,
                      background: densityColor(n),
                    }}
                    onClick={() => {
                      setAnchor(d);
                      setMode("day");
                    }}
                  >
                    <div style={{ fontSize: 13 }}>{d.getDate()}</div>
                    {n ? (
                      <div
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background:
                            n > 5 ? "#fff" : "var(--sd-link)",
                        }}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* Day 视图：当日事件列表 */}
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              fontSize: 12,
              color: "var(--sd-text-3)",
              margin: "12px 0 8px",
            }}
          >
            {t("staffdeck.timeline.dayEvents", "当日事件")}
          </div>
          {dayEvents.length === 0 ? (
            <div
              style={{
                border: "0.5px dashed var(--sd-line)",
                borderRadius: "var(--sd-radius-lg)",
                padding: "28px 0",
                textAlign: "center",
                color: "var(--sd-text-3)",
                fontSize: 13,
              }}
            >
              {t("staffdeck.timeline.empty", "当日暂无活动记录")}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {dayEvents.map((e, i) => (
                <div
                  key={`${e.kind}-${i}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                    border: "0.5px solid var(--sd-line)",
                    borderRadius: "var(--sd-radius-lg)",
                  }}
                >
                  <span style={{ fontSize: 12, color: "var(--sd-text-3)", width: 44 }}>
                    {(e.at || "").slice(11, 16) || "--"}
                  </span>
                  <span
                    style={{
                      flex: 1,
                      fontSize: 13,
                      color: "var(--sd-ink)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {e.title}
                  </span>
                  <StatusPill
                    tone={
                      e.status === "succeeded" || e.status === "published"
                        ? "green"
                        : e.status === "failed"
                          ? "red"
                          : "gray"
                    }
                  >
                    {e.status}
                  </StatusPill>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  border: "0.5px solid var(--sd-line)",
  background: "#fff",
  borderRadius: "var(--sd-radius-sm)",
  cursor: "pointer",
  fontSize: 13,
  color: "var(--sd-text-2)",
  padding: "3px 10px",
};
