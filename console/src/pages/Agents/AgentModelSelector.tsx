/**
 * AgentModelSelector.tsx — 员工默认模型选择器（档案区紧凑 pill 下拉）。
 *
 * 读写员工级默认模型（PUT /models/active scope=agent）：后端同步落
 * agent.json 与 agent_model_slots PG 平面并热重载，即该数字员工后台
 * 默认运行模型。未来前台用户指定模型走请求级覆盖不落盘，未指定时
 * 使用此处配置——前台选择不影响本配置。
 *
 * 显示语义：员工已单独配置 → 显示配置值；未配置 → 显示当前生效值
 * （全局默认回退）并附「跟随全局默认」徽标。模型清单经
 * listSelectableModels 过滤禁用项（与聊天页选择器同一契约）。
 * 数据零新接口：providerApi providers 清单 + agent/effective 双 scope。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Dropdown } from "antd";
import { useTranslation } from "react-i18next";
import { ChevronDown, Cpu } from "lucide-react";
import { providerApi } from "@/api/modules/provider";
import type { ActiveModelsInfo, ProviderInfo } from "@/api/types";
import type { ModelSlotConfig } from "@/api/types/provider";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  buildEligibleProviders,
  modelKey,
} from "@/pages/Chat/ModelSelector/modelSelectorModels";
import styles from "./detail.module.less";

interface AgentModelSelectorProps {
  /** 数据域员工 ID（URL :aid / selectedAgent 同源）。 */
  agentId: string;
  /** 是否渲染「模型」文字前缀（左栏元信息已有 dt 标签时传 false）。 */
  showLabel?: boolean;
}

export default function AgentModelSelector({
  agentId,
  showLabel = true,
}: AgentModelSelectorProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [agentActive, setAgentActive] = useState<ActiveModelsInfo | null>(
    null,
  );
  const [effectiveActive, setEffectiveActive] =
    useState<ActiveModelsInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [providersResult, agentResult, effectiveResult] =
      await Promise.allSettled([
        providerApi.listProviders(),
        providerApi.getActiveModels({ scope: "agent", agent_id: agentId }),
        providerApi.getActiveModels({ scope: "effective", agent_id: agentId }),
      ]);
    setProviders(
      providersResult.status === "fulfilled" ? providersResult.value : [],
    );
    setAgentActive(agentResult.status === "fulfilled" ? agentResult.value : null);
    setEffectiveActive(
      effectiveResult.status === "fulfilled" ? effectiveResult.value : null,
    );
    setLoading(false);
  }, [agentId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // 展示值：员工配置优先，未配置回退生效值（全局默认）
  const displaySlot: ModelSlotConfig | null =
    agentActive?.active_llm ?? effectiveActive?.active_llm ?? null;
  const isFollowingGlobal = !agentActive?.active_llm && !!displaySlot;

  const displayName = useMemo(() => {
    if (!displaySlot) return "—";
    const provider = providers.find((p) => p.id === displaySlot.provider_id);
    const model = provider
      ? [...(provider.models ?? []), ...(provider.extra_models ?? [])].find(
          (m) => m.id === displaySlot.model,
        )
      : undefined;
    return model?.name || displaySlot.model;
  }, [displaySlot, providers]);

  // 下拉菜单：按 provider 分组的模型清单（已过滤禁用项）
  const menuItems = useMemo(() => {
    return buildEligibleProviders(providers).map((provider) => ({
      key: provider.id,
      type: "group" as const,
      label: provider.name,
      children: provider.models.map((model) => ({
        key: modelKey(provider.id, model.id),
        label: model.name || model.id,
      })),
    }));
  }, [providers]);

  const handleSelect = useCallback(
    async ({ key }: { key: string }) => {
      const separator = key.indexOf(":");
      if (separator <= 0 || saving) return;
      const providerId = key.slice(0, separator);
      const modelId = key.slice(separator + 1);
      if (displaySlot?.provider_id === providerId && displaySlot?.model === modelId) {
        return;
      }
      setSaving(true);
      try {
        await providerApi.setActiveLlm({
          provider_id: providerId,
          model: modelId,
          scope: "agent",
          agent_id: agentId,
        });
        message.success(
          t("agentDetail.modelSelectorUpdateOk", "默认模型已更新，对话即时生效"),
        );
        await loadData();
      } catch {
        message.error(
          t("agentDetail.modelSelectorSaveFail", "默认模型保存失败，请重试"),
        );
      } finally {
        setSaving(false);
      }
    },
    [agentId, displaySlot, loadData, message, saving, t],
  );

  return (
    <div className={styles.modelSelectorRow}>
      {showLabel && (
        <span className={styles.modelSelectorLabel}>
          {t("agentDetail.modelSelectorLabel", "模型")}
        </span>
      )}
      <Dropdown
        trigger={["click"]}
        menu={{
          items: menuItems,
          onClick: (info) => void handleSelect(info),
          style: { maxHeight: 360, overflowY: "auto" },
        }}
      >
        <button
          type="button"
          className={styles.modelPill}
          disabled={loading || saving || menuItems.length === 0}
          title={t("agentDetail.modelSelectorTitle", "配置该员工后台默认运行的模型")}
        >
          <Cpu size={13} className={styles.modelPillIcon} />
          <span className={styles.modelPillValue} title={displayName}>
            {loading && !displaySlot ? "…" : displayName}
          </span>
          <ChevronDown size={12} className={styles.modelPillChevron} />
        </button>
      </Dropdown>
      {isFollowingGlobal && (
        <span
          className={styles.modelFollowTag}
          title={t(
            "agentDetail.modelFollowGlobalTitle",
            "该员工未单独配置模型，当前跟随全局默认；选择上方模型即设为本员工专属默认",
          )}
        >
          {t("agentDetail.modelFollowGlobal", "跟随全局默认")}
        </span>
      )}
    </div>
  );
}
