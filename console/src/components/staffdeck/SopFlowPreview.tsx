/**
 * staffdeck/SopFlowPreview.tsx — SOP 只读流程图预览（补全项③）。
 *
 * 竖向流程：节点卡（步骤标题 + 验收要点）+ 条件边标注。自绘轻量实现
 * （CSS 层级 + 连接线），不引入图库——SOP 在本系统的定位是"经验路径
 * 参考"，预览重在可读性而非画布编辑。
 */
import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { sopApi, type SopRecord } from "@/api/modules/admin";
import { StatusPill } from "./StatusPill";

export function SopFlowPreview({ sopId }: { sopId: string }) {
  const { t } = useTranslation();
  const [sop, setSop] = useState<SopRecord | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    sopApi
      .get(sopId)
      .then((s) => {
        if (!cancelled) setSop(s);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [sopId]);

  if (error) {
    return <div style={{ color: "var(--sd-red)", fontSize: 13 }}>{error}</div>;
  }
  if (!sop) {
    return (
      <div style={{ color: "var(--sd-text-3)", fontSize: 13 }}>
        {t("staffdeck.sop.loading", "加载中…")}
      </div>
    );
  }

  const nodes = sop.nodes ?? [];
  const edgeCondition = (fromId: string) => {
    const edge = (sop.edges ?? []).find((e) => e.from === fromId);
    return edge?.condition?.trim() || "";
  };

  return (
    <div>
      {/* 元信息 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 16, fontWeight: 600, color: "var(--sd-ink)" }}>
          {sop.name}
        </span>
        <StatusPill
          tone={sop.status === "published" ? "green" : sop.status === "draft" ? "blue" : "gray"}
        >
          {sop.status}
        </StatusPill>
        <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>v{sop.version}</span>
      </div>
      {sop.goal ? (
        <div style={{ marginTop: 8, fontSize: 13, color: "var(--sd-text-4)", lineHeight: "20px" }}>
          {t("staffdeck.sop.goal", "目标")}：{sop.goal}
        </div>
      ) : null}
      {sop.description ? (
        <div style={{ marginTop: 4, fontSize: 12, color: "var(--sd-text-2)", lineHeight: "18px" }}>
          {sop.description}
        </div>
      ) : null}

      {/* 竖向节点流 */}
      <div style={{ marginTop: 18, display: "flex", flexDirection: "column", alignItems: "stretch" }}>
        {nodes.length === 0 ? (
          <div
            style={{
              border: "0.5px dashed var(--sd-line)",
              borderRadius: "var(--sd-radius-lg)",
              padding: "24px 0",
              textAlign: "center",
              color: "var(--sd-text-3)",
              fontSize: 13,
            }}
          >
            {t("staffdeck.sop.noNodes", "该 SOP 还没有步骤节点")}
          </div>
        ) : (
          nodes.map((node, index) => {
            const condition = index < nodes.length - 1 ? edgeCondition(String(node.id)) : "";
            return (
              <React.Fragment key={String(node.id ?? index)}>
                {/* 节点卡 */}
                <div
                  style={{
                    border: "0.5px solid var(--sd-line)",
                    borderRadius: "var(--sd-radius-lg)",
                    padding: "12px 16px",
                    background: "var(--sd-card)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        background: "var(--sd-ink)",
                        color: "#fff",
                        fontSize: 12,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    >
                      {index + 1}
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
                      {node.title || node.id}
                    </span>
                    {(node.tools ?? []).length > 0 ? (
                      <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                        {t("staffdeck.sop.tools", "工具")}：{(node.tools ?? []).join("、")}
                      </span>
                    ) : null}
                  </div>
                  {node.instruction ? (
                    <div style={{ marginTop: 6, fontSize: 13, color: "var(--sd-text-4)", lineHeight: "20px" }}>
                      {node.instruction}
                    </div>
                  ) : null}
                  {node.expected_outcome ? (
                    <div
                      style={{
                        marginTop: 8,
                        fontSize: 12,
                        color: "var(--sd-green)",
                        background: "var(--sd-green-bg)",
                        borderRadius: "var(--sd-radius-sm)",
                        padding: "4px 10px",
                        display: "inline-block",
                      }}
                    >
                      {t("staffdeck.sop.acceptance", "验收要点")}：{node.expected_outcome}
                    </div>
                  ) : null}
                </div>
                {/* 连接线 + 条件标注 */}
                {index < nodes.length - 1 ? (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "2px 0" }}>
                    <div style={{ width: 1, height: 14, background: "var(--sd-line)" }} />
                    {condition ? (
                      <span style={{ fontSize: 11, color: "var(--sd-text-3)", padding: "1px 0" }}>
                        {condition}
                      </span>
                    ) : null}
                    <div style={{ width: 1, height: 14, background: "var(--sd-line)" }} />
                  </div>
                ) : null}
              </React.Fragment>
            );
          })
        )}
      </div>
    </div>
  );
}
