/**
 * workbench/WorkbenchSopCanvasPage.tsx — 工作台 SOP 画布下钻页（/studio/:aid/sop/:sopId）。
 *
 * 对齐运行日志详情页的下钻模式：URL 驱动 + 返回按钮 + 占满顶栏以下内容区，
 * 取代原 94vw Drawer 弹窗（画布编辑页面化，20260916）。外壳在画布页激活期间
 * 以 display:none 保活 workbenchBody，关闭后聊天会话与右侧 Tab 状态原样恢复。
 *
 * 数据域自解析：与 RunLogDetailPage 的沙箱模式一致，aid/sopId 从
 * pathname 解析（外壳经 lazyImportWithRetry 无 props 渲染，URL 直达/
 * 刷新均成立）；expertId 由 aid 前缀换算。挂载时 ensureDraft 拉草稿
 * （存量线上 SOP 自动 fork 工作副本，幂等）；AI 侧实时重绘由
 * SopFlowCanvas 内部的 sop 级订阅负责。
 * @author qingfeng
 */
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import { SopFlowCanvas } from "@/components/sop/SopFlowCanvas";
import { useAppMessage } from "@/hooks/useAppMessage";
import { sopApi, type SopRecord } from "@/api/modules/admin";
import styles from "./workbench.module.less";

export default function WorkbenchSopCanvasPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const navigate = useNavigate();
  const location = useLocation();
  // 自解析数据域：/studio/:aid/sop/:sopId（沙箱无 <Route> 匹配，无 useParams）
  const parsed = location.pathname.match(/^\/studio\/([^/]+)\/sop\/([^/?#]+)/);
  const aid = parsed?.[1] ?? "";
  const sopId = parsed?.[2] ?? "";
  // 返回目标：打开画布时的来源页（外壳/面板导航时经 state 传入）；
  // URL 直达/刷新无 state 时兜底到能力-SOP 列表。
  const backTarget =
    (location.state as { from?: string } | null)?.from ||
    `/studio/${aid}/capability/sop`;

  const [sop, setSop] = useState<SopRecord | null>(null);
  const [loadError, setLoadError] = useState("");

  // 拉取可编辑草稿（幂等 fork），sopId 变化（AI 连续创建新 SOP）时重载
  useEffect(() => {
    if (!sopId) {
      return;
    }
    let cancelled = false;
    setSop(null);
    setLoadError("");
    void (async () => {
      try {
        const draft = await sopApi.ensureDraft(sopId);
        if (!cancelled) {
          setSop(draft);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sopId]);

  const goBack = useCallback(
    () => navigate(backTarget),
    [backTarget, navigate],
  );

  return (
    <div className={styles.sopCanvasPage}>
      {/* ── 页顶栏：返回 + 标题 + 发布引导提示（发布收敛到员工顶栏统一闸门） ── */}
      <div className={styles.sopCanvasTopbar}>
        <button
          type="button"
          className={styles.headerBtn}
          title={t("staffdeck.canvas.backToList", "返回 SOP 列表")}
          onClick={goBack}
        >
          <ArrowLeft size={15} />
        </button>
        <span className={styles.sopCanvasTitle}>
          {sop
            ? `${t("staffdeck.canvas.editorTitle", "SOP 画布编辑")} · ${sop.name} (v${sop.version})`
            : t("staffdeck.canvas.editorTitle", "SOP 画布编辑")}
        </span>
        <span className={styles.headerSpacer} />
        <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
          {t(
            "staffdeck.canvas.publishViaTopbar",
            "编辑后点右上角『发布』对员工生效",
          )}
        </span>
      </div>

      {/* ── 主体：加载/错误态 + 画布 ── */}
      {loadError ? (
        <div className={styles.sopCanvasMessage}>{loadError}</div>
      ) : !sop ? (
        <div className={styles.sopCanvasMessage}>
          <Spin />
        </div>
      ) : (
        <div className={styles.sopCanvasHost}>
          <SopFlowCanvas
            sop={sop}
            onSave={async (payload) => {
              try {
                const updated = await sopApi.update(sop.id, {
                  nodes: payload.nodes,
                  edges: payload.edges,
                  slots: payload.slots,
                });
                // 同步标题里的版本号；画布内容不重置（SopFlowCanvas
                // 仅初始化时消费 sop prop，实时重绘走内部订阅）
                setSop(updated);
                message.success(t("staffdeck.canvas.saved", "已保存"));
              } catch (err) {
                message.error(String(err));
              }
            }}
          />
        </div>
      )}
    </div>
  );
}
