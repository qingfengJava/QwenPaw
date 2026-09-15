/**
 * workbench/WorkbenchSopTab.tsx — 工作台「能力-SOP」子页（SOP 私有能力化，20260914）。
 *
 * 借壳页面模式：数据域（selectedAgent）由工作台外壳同步，本页只做
 * `expert_` 前缀 → 专家域 id 的换算并托管 ExpertSopPanel；外壳已按
 * isExpert 过滤该 Tab，非 expert 实例兜底渲染空态不报错。
 * @author qingfeng
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "@/stores/agentStore";
import { ExpertSopPanel } from "@/components/sop/ExpertSopPanel";

export default function WorkbenchSopTab() {
  const { t } = useTranslation();
  // 外壳在 layout 阶段把当前员工 aid 同步进 selectedAgent，与其它借壳页一致
  const aid = useAgentStore((s) => s.selectedAgent);
  // 运行时 agent id = expert_{expertId}；草稿实例（__draft）不允许在此配置
  const expertId = useMemo(() => {
    if (aid.startsWith("expert_") && !aid.includes("__draft")) {
      return aid.slice("expert_".length);
    }
    return "";
  }, [aid]);

  if (!expertId) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--sd-text-3)" }}>
        {t("staffdeck.sopPanel.nativeEmpty", "该实例不是数字员工，暂不支持 SOP 配置")}
      </div>
    );
  }

  return <ExpertSopPanel expertId={expertId} onChanged={() => {}} />;
}
