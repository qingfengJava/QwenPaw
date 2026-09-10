import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, InputNumber, Slider, Switch } from "@agentscope-ai/design";
import { Segmented } from "antd";
import { Check, RotateCcw } from "lucide-react";
import type {
  AgentModelOverrides,
  ModelInfo,
  ProviderInfo,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { formatTokenCount } from "../../../../../utils/tokenFormat";
import { JsonConfigEditor } from "./JsonConfigEditor";

function requestMaxTokens(model: ModelInfo): number | null {
  const value = model.generate_kwargs?.max_tokens;
  return typeof value === "number" ? value : null;
}

function editableGenerateConfig(
  generateKwargs: Record<string, unknown>,
): Record<string, unknown> {
  const config = { ...generateKwargs };
  delete config.max_tokens;
  return config;
}

export function ModelConfigEditor({
  providerId,
  model,
  onSaved,
  onProviderUpdated,
  onClose,
  isDark,
  thinkingParamStyle,
  reasoningEffortOptions,
  thinkingBudgetRange = [1, 81920],
  chatModel,
  compact = false,
  agentScope = null,
}: {
  providerId: string;
  model: ModelInfo;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
  onClose: () => void;
  isDark: boolean;
  thinkingParamStyle?: "budget" | "effort" | null;
  reasoningEffortOptions?: string[];
  thinkingBudgetRange?: [number, number];
  chatModel?: string;
  /** 精简模式：使用现场侧栏用，只留上下文档位 + 思考模式，隐藏进阶项 */
  compact?: boolean;
  /** 员工域模式：编辑员工专属模型参数覆盖（写入员工槽位，不触全局基线） */
  agentScope?: {
    agentId: string;
    overrides: AgentModelOverrides | null;
  } | null;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const configuredMaxTokens = requestMaxTokens(model);

  const [maxTokens, setMaxTokens] = useState<number | null>(
    configuredMaxTokens,
  );
  const [maxInputLength, setMaxInputLength] = useState<number | null>(
    model.max_input_length ?? 131072,
  );
  const [maxInputLengthDirty, setMaxInputLengthDirty] = useState(false);
  const [relayReasoning, setRelayReasoning] = useState<boolean>(
    model.relay_reasoning ?? true,
  );
  const [thinkingEnabled, setThinkingEnabled] = useState<boolean | null>(
    model.thinking_enabled ?? null,
  );
  const [thinkingBudget, setThinkingBudget] = useState<number | null>(
    model.thinking_budget ?? null,
  );
  const [reasoningEffort, setReasoningEffort] = useState<string | null>(
    model.reasoning_effort ?? null,
  );

  const initialText = useMemo(() => {
    const config = editableGenerateConfig(model.generate_kwargs);
    return Object.keys(config).length > 0
      ? JSON.stringify(config, null, 2)
      : "";
  }, [model.generate_kwargs]);

  const [text, setText] = useState(initialText);
  const [dirty, setDirty] = useState(false);

  // --- 员工域覆盖状态（仅 agentScope 模式使用；字段 null=跟随全局基线）---
  // 初值来自后端下发；保存后本地同步为最新覆盖集（编辑器生命周期内唯一来源）
  const [agentOverrides, setAgentOverrides] = useState<AgentModelOverrides>(
    () => ({ ...(agentScope?.overrides ?? {}) }),
  );

  useEffect(() => {
    setText(initialText);
    setMaxTokens(configuredMaxTokens);
    // 员工域：展示值 = 员工覆盖 ?? 全局模型配置（回退基线可见）
    const ov = agentScope ? agentOverrides : {};
    setMaxInputLength(ov.max_input_length ?? model.max_input_length ?? 131072);
    setMaxInputLengthDirty(false);
    setRelayReasoning(model.relay_reasoning ?? true);
    setThinkingEnabled(ov.thinking_enabled ?? model.thinking_enabled ?? null);
    setThinkingBudget(ov.thinking_budget ?? model.thinking_budget ?? null);
    setReasoningEffort(ov.reasoning_effort ?? model.reasoning_effort ?? null);
    setDirty(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- agentOverrides 仅作回退源，不参与依赖避免交互后被重置
  }, [
    initialText,
    configuredMaxTokens,
    model.max_input_length,
    model.relay_reasoning,
    model.thinking_enabled,
    model.thinking_budget,
    model.reasoning_effort,
  ]);

  const effectiveMaxInputLength = maxInputLength ?? 131072;

  // 上下文窗口建议档位：探测值优先 + 通用档（128K/200K/400K/1M），
  // 去重升序；当前值不在档位内时也加入（保证选中态可见），最多 7 档
  const contextPresets = useMemo(() => {
    const values = new Set<number>([131072, 204800, 409600, 1048576]);
    if (model.max_input_length_auto_detected) {
      values.add(model.max_input_length_auto_detected);
    }
    if (maxInputLength) {
      values.add(maxInputLength);
    }
    return [...values].sort((a, b) => a - b).slice(0, 7);
  }, [model.max_input_length_auto_detected, maxInputLength]);
  
  // 精简模式的档位标注：供应商探测/默认值标「默认」，用户改过的当前值标「已自定义」
  const presetSuffix = (value: number): string | null => {
    // 员工域：员工覆盖值优先标「员工专属」，其余保持全局来源标注
    if (agentScope && agentOverrides.max_input_length === value) {
      return t("modelSelector.agentOverrideTag");
    }
    if (
      value === model.max_input_length_auto_detected ||
      (!model.max_input_length_auto_detected && value === 131072)
    ) {
      return t("modelSelector.contextDefault");
    }
    if (
      model.max_input_length_configured &&
      value === model.max_input_length
    ) {
      return t("modelSelector.contextCustomized");
    }
    return null;
  };

  // 精简模式下 budget 型模型的思考档位：由模型预算范围推导 低/中/高 + 默认
  const budgetLevels: { label: string; value: number | null }[] = [
    { label: t("models.switchToAuto"), value: null },
    {
      label: t("modelSelector.thinking.low"),
      value: Math.max(
        thinkingBudgetRange[0],
        Math.round(thinkingBudgetRange[1] * 0.25),
      ),
    },
    {
      label: t("modelSelector.thinking.medium"),
      value: Math.max(
        thinkingBudgetRange[0],
        Math.round(thinkingBudgetRange[1] * 0.5),
      ),
    },
    { label: t("modelSelector.thinking.high"), value: thinkingBudgetRange[1] },
  ];

  const handleChange = useCallback((val: string) => {
    setText(val);
    setDirty(true);
  }, []);

  const handleMaxTokensChange = useCallback((val: number | null) => {
    setMaxTokens(val);
    setDirty(true);
  }, []);

  const handleMaxInputLengthChange = useCallback((val: number | null) => {
    setMaxInputLength(val);
    setMaxInputLengthDirty(true);
    setDirty(true);
  }, []);

  /** 组装 generate_kwargs 负载（完整/精简模式共用）；JSON 非法时返回 null */
  const buildGenerateKwargs = (): Record<string, unknown> | null => {
    const trimmed = text.trim();
    let parsed: Record<string, unknown> = {};
    if (trimmed) {
      try {
        const obj = JSON.parse(trimmed);
        if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
          message.error(t("models.generateConfigMustBeObject"));
          return null;
        }
        parsed = obj;
        delete parsed.max_tokens;
      } catch {
        message.error(t("models.generateConfigInvalidJson"));
        return null;
      }
    }
    if (maxTokens !== null) {
      parsed.max_tokens = maxTokens;
    }
    return parsed;
  };

  /** 员工域保存：整体替换员工覆盖集（字段 null=清除回全局基线），选择即存 */
  const persistAgentConfig = async (
    delta: Partial<AgentModelOverrides> = {},
  ) => {
    if (!agentScope) {
      return;
    }
    const next: AgentModelOverrides = {
      max_input_length:
        delta.max_input_length !== undefined
          ? delta.max_input_length
          : (agentOverrides.max_input_length ?? null),
      thinking_enabled:
        delta.thinking_enabled !== undefined
          ? delta.thinking_enabled
          : (agentOverrides.thinking_enabled ?? null),
      thinking_budget:
        delta.thinking_budget !== undefined
          ? delta.thinking_budget
          : (agentOverrides.thinking_budget ?? null),
      reasoning_effort:
        delta.reasoning_effort !== undefined
          ? delta.reasoning_effort
          : (agentOverrides.reasoning_effort ?? null),
    };
    setAgentOverrides(next);
    setSaving(true);
    try {
      await api.setActiveLlm({
        provider_id: providerId,
        model: model.id,
        scope: "agent",
        agent_id: agentScope.agentId,
        overrides: next,
      });
      // 选择即存：不打断操作，不弹成功提示（失败仍有错误提示）
      // 刷新员工生效模型元数据（上下文徽标/思考标记立即跟随）
      await onSaved();
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  /** 员工域：恢复上下文窗口为跟随全局基线 */
  const clearContextOverride = () => {
    setMaxInputLength(model.max_input_length ?? 131072);
    void persistAgentConfig({ max_input_length: null });
  };

  /** 员工域：恢复思考参数为跟随全局基线 */
  const clearThinkingOverride = () => {
    setThinkingEnabled(model.thinking_enabled ?? null);
    setThinkingBudget(model.thinking_budget ?? null);
    setReasoningEffort(model.reasoning_effort ?? null);
    void persistAgentConfig({
      thinking_enabled: null,
      thinking_budget: null,
      reasoning_effort: null,
    });
  };

  const thinkingOverridden =
    agentScope != null &&
    (agentOverrides.thinking_enabled != null ||
      agentOverrides.thinking_budget != null ||
      agentOverrides.reasoning_effort != null);

  /** 保存模型配置：完整模式走保存按钮；精简模式选择即存（overrides 优先于 state） */
  const persistConfig = async (
    overrides: {
      maxInputLength?: number;
      thinkingEnabled?: boolean;
      thinkingBudget?: number | null;
      reasoningEffort?: string | null;
    } = {},
  ) => {
    const parsed = buildGenerateKwargs();
    if (parsed === null) {
      return;
    }
    const nextThinkingEnabled =
      overrides.thinkingEnabled !== undefined
        ? overrides.thinkingEnabled
        : thinkingEnabled;
    const nextThinkingBudget =
      overrides.thinkingBudget !== undefined
        ? overrides.thinkingBudget
        : thinkingBudget;
    const nextReasoningEffort =
      overrides.reasoningEffort !== undefined
        ? overrides.reasoningEffort
        : reasoningEffort;
    const nextMaxInputLength =
      overrides.maxInputLength !== undefined
        ? overrides.maxInputLength
        : effectiveMaxInputLength;

    // 员工域：转员工覆盖保存，绝不触碰全局模型配置
    if (agentScope) {
      const delta: Partial<AgentModelOverrides> = {};
      if (overrides.maxInputLength !== undefined) {
        delta.max_input_length = overrides.maxInputLength;
      }
      if (overrides.thinkingEnabled !== undefined) {
        delta.thinking_enabled = overrides.thinkingEnabled;
      }
      if (overrides.thinkingBudget !== undefined) {
        delta.thinking_budget = overrides.thinkingBudget;
      }
      if (overrides.reasoningEffort !== undefined) {
        delta.reasoning_effort = overrides.reasoningEffort;
      }
      await persistAgentConfig(delta);
      return;
    }

    setSaving(true);
    try {
      const updated = await api.configureModel(providerId, model.id, {
        ...(overrides.maxInputLength !== undefined || maxInputLengthDirty
          ? { max_input_length: nextMaxInputLength }
          : {}),
        generate_kwargs: parsed,
        relay_reasoning: relayReasoning,
        thinking_enabled: nextThinkingEnabled,
        thinking_budget: nextThinkingBudget,
        reasoning_effort: nextReasoningEffort,
      });
      setDirty(false);
      setMaxInputLengthDirty(false);
      // 本地增量回调保留：精简模式靠它让左侧列表 badge 立即跟随变化（无网络请求）
      onProviderUpdated?.(updated);
      // 精简模式选择即存：静默保存，不弹提示、不触发外部全量刷新
      if (!compact) {
        message.success(t("models.modelConfigSaved", { name: model.name }));
        await onSaved();
        onClose();
      }
    } catch (error) {
      const errMsg =
        error instanceof Error
          ? error.message
          : t("models.modelConfigSaveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => {
    void persistConfig();
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 13,
    color: isDark ? "rgba(255,255,255,0.85)" : "#333",
    marginBottom: 4,
  };

  return (
    <div style={{ padding: "8px 0 4px" }}>
      {/* 精简模式：只保留上下文档位列表 + 思考模式，选择即保存 */}
      {compact && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ ...labelStyle, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>{t("models.maxInputLengthLabel", "Max Context Length")}</span>
            {agentScope && agentOverrides.max_input_length != null && (
              <a
                style={{ fontSize: 11, cursor: "pointer" }}
                onClick={clearContextOverride}
                title={t("modelSelector.followGlobalHint")}
              >
                {t("modelSelector.followGlobalReset")}
              </a>
            )}
          </div>
          {contextPresets.map((value) => {
            const selected = maxInputLength === value;
            const suffix = presetSuffix(value);
            return (
              <button
                key={value}
                type="button"
                onClick={() => {
                  handleMaxInputLengthChange(value);
                  void persistConfig({ maxInputLength: value });
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  width: "100%",
                  padding: "7px 10px",
                  marginBottom: 4,
                  border: "none",
                  borderRadius: 8,
                  fontSize: 13,
                  textAlign: "left",
                  cursor: "pointer",
                  color: isDark ? "rgba(255,255,255,0.85)" : "#333",
                  background: selected
                    ? isDark
                      ? "rgba(255,255,255,0.08)"
                      : "rgba(0,0,0,0.04)"
                    : "transparent",
                }}
              >
                <span>
                  {formatTokenCount(value)}
                  {suffix ? ` ${suffix}` : ""}
                </span>
                {selected && <Check size={14} />}
              </button>
            );
          })}
        </div>
      )}
      {!compact && (
      <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
        <div style={{ flex: 1 }}>
          <div
            style={{
              ...labelStyle,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span>{t("models.maxTokensLabel", "Max Tokens")}</span>
            {maxTokens !== null && (
              <Button
                type="text"
                size="small"
                icon={<RotateCcw size={14} />}
                aria-label={t("models.resetMaxTokens", "Reset to auto")}
                title={t("models.resetMaxTokens", "Reset to auto")}
                onClick={() => handleMaxTokensChange(null)}
              />
            )}
          </div>
          <InputNumber
            style={{ width: "100%" }}
            min={1}
            step={1024}
            value={maxTokens}
            placeholder={t("models.providerDefault", "Provider default")}
            onChange={handleMaxTokensChange}
          />
          <div
            style={{
              fontSize: 11,
              color: isDark ? "rgba(255,255,255,0.35)" : "#999",
              marginTop: 2,
            }}
          >
            {t("models.maxTokensHint", "每次响应的最大输出 token 数")}
            <br />
            {t("models.maxOutputCapabilityLabel", "Model capability")}:{" "}
            {model.max_output_length?.toLocaleString() ??
              t("models.unknown", "Unknown")}
            {model.max_output_length_source &&
              model.max_output_length_source !== "unknown" && (
                <> · {model.max_output_length_source}</>
              )}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={labelStyle}>
            {t("models.maxInputLengthLabel", "Max Context Length")}
          </div>
          <InputNumber
            style={{ width: "100%" }}
            min={1000}
            step={1024}
            value={maxInputLength}
            placeholder="131072"
            onChange={handleMaxInputLengthChange}
          />
          <Segmented
            block
            size="small"
            style={{ marginTop: 4 }}
            value={maxInputLength}
            onChange={(val) => handleMaxInputLengthChange(val as number)}
            options={contextPresets.map((value) => ({
              label: formatTokenCount(value),
              value,
            }))}
          />
          <div
            style={{
              fontSize: 11,
              color: isDark ? "rgba(255,255,255,0.35)" : "#999",
              marginTop: 2,
            }}
          >
            {t(
              "models.maxInputLengthHint",
              "模型上下文窗口大小，控制上下文压缩阈值（≥1000）",
            )}
            {model.max_input_length_auto_detected != null && (
              <>
                <br />
                {t("modelSelector.contextDetected")}:{" "}
                {formatTokenCount(model.max_input_length_auto_detected)}
              </>
            )}
          </div>
        </div>
      </div>
      )}
      {/* Enable Thinking (only for providers that support thinking config) */}
      {thinkingParamStyle && (
        <>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 8,
              padding: "6px 0",
            }}
          >
            <div>
              <span
                style={{
                  fontSize: 13,
                  color: isDark ? "rgba(255,255,255,0.85)" : "#333",
                }}
              >
                {t("models.thinkingModeLabel")}
              </span>
              {agentScope && thinkingOverridden && (
                <a
                  style={{ fontSize: 11, cursor: "pointer", marginLeft: 8 }}
                  onClick={clearThinkingOverride}
                  title={t("modelSelector.followGlobalHint")}
                >
                  {t("modelSelector.followGlobalReset")}
                </a>
              )}
              {!compact && (
                <div
                  style={{
                    fontSize: 11,
                    color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                    marginTop: 2,
                  }}
                >
                  {t("models.thinkingModeHint")}
                </div>
              )}
            </div>
            <Switch
              checked={thinkingEnabled === true}
              onChange={(checked) => {
                setThinkingEnabled(checked);
                if (compact) {
                  // 精简模式选择即存
                  void persistConfig({ thinkingEnabled: checked });
                } else {
                  setDirty(true);
                }
              }}
            />
          </div>

          {thinkingEnabled === true && (
            <div style={{ marginBottom: 12 }}>
              {thinkingParamStyle === "budget" ? (
                compact ? (
                  <div>
                    {budgetLevels.map((level) => {
                      const selected = thinkingBudget === level.value;
                      return (
                        <button
                          key={String(level.value)}
                          type="button"
                          onClick={() => {
                            setThinkingBudget(level.value);
                            void persistConfig({ thinkingBudget: level.value });
                          }}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            width: "100%",
                            padding: "7px 10px",
                            marginBottom: 4,
                            border: "none",
                            borderRadius: 8,
                            fontSize: 13,
                            textAlign: "left",
                            cursor: "pointer",
                            color: isDark ? "rgba(255,255,255,0.85)" : "#333",
                            background: selected
                              ? isDark
                                ? "rgba(255,255,255,0.08)"
                                : "rgba(0,0,0,0.04)"
                              : "transparent",
                          }}
                        >
                          <span>{level.label}</span>
                          {selected && <Check size={14} />}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                <div>
                  <div
                    style={{
                      ...labelStyle,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <span>{t("models.thinkingBudgetLabel")}</span>
                    <a
                      style={{ fontSize: 11, cursor: "pointer" }}
                      onClick={() => {
                        setThinkingBudget(
                          thinkingBudget === null
                            ? thinkingBudgetRange[0]
                            : null,
                        );
                        setDirty(true);
                      }}
                    >
                      {thinkingBudget === null
                        ? t("models.switchToManual")
                        : t("models.switchToAuto")}
                    </a>
                  </div>
                  {thinkingBudget !== null ? (
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 12 }}
                    >
                      <div style={{ flex: 1 }}>
                        <Slider
                          min={thinkingBudgetRange[0]}
                          max={thinkingBudgetRange[1]}
                          step={1024}
                          value={thinkingBudget}
                          onChange={(val: number) => {
                            setThinkingBudget(val);
                            setDirty(true);
                          }}
                          onChangeComplete={(val: number) => {
                            // 精简模式拖动结束后即存，避免滑动过程连发请求
                            if (compact) {
                              void persistConfig({ thinkingBudget: val });
                            }
                          }}
                        />
                      </div>
                      {!compact && (
                        <InputNumber
                          style={{ width: 100 }}
                          min={thinkingBudgetRange[0]}
                          max={thinkingBudgetRange[1]}
                          step={1024}
                          value={thinkingBudget}
                          onChange={(val) => {
                            setThinkingBudget(val);
                            setDirty(true);
                          }}
                        />
                      )}
                    </div>
                  ) : (
                    <div
                      style={{
                        fontSize: 11,
                        color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                        marginTop: 2,
                      }}
                    >
                      {t("models.thinkingBudgetHint")}
                    </div>
                  )}
                </div>
                )
              ) : (
                <div>
                  <div style={labelStyle}>
                    {t("models.reasoningEffortLabel")}
                  </div>
                  {/* 精简模式：按模型支持的档位渲染竖排列表，选择即存；
                      完整模式：保持横向 Segmented */}
                  {compact ? (
                    <div>
                      {[
                        {
                          label: t("models.switchToAuto"),
                          value: "__auto__",
                        },
                        ...(
                          reasoningEffortOptions ?? [
                            "none",
                            "minimal",
                            "low",
                            "medium",
                            "high",
                            "xhigh",
                          ]
                        ).map((v) => ({
                          label: v.charAt(0).toUpperCase() + v.slice(1),
                          value: v,
                        })),
                      ].map((option) => {
                        const selected =
                          (reasoningEffort ?? "__auto__") === option.value;
                        return (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => {
                              const next =
                                option.value === "__auto__"
                                  ? null
                                  : option.value;
                              setReasoningEffort(next);
                              void persistConfig({ reasoningEffort: next });
                            }}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              width: "100%",
                              padding: "7px 10px",
                              marginBottom: 4,
                              border: "none",
                              borderRadius: 8,
                              fontSize: 13,
                              textAlign: "left",
                              cursor: "pointer",
                              color:
                                isDark ? "rgba(255,255,255,0.85)" : "#333",
                              background: selected
                                ? isDark
                                  ? "rgba(255,255,255,0.08)"
                                  : "rgba(0,0,0,0.04)"
                                : "transparent",
                            }}
                          >
                            <span>{option.label}</span>
                            {selected && <Check size={14} />}
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <Segmented
                      block
                      value={reasoningEffort ?? "__auto__"}
                      onChange={(val) => {
                        const v = val as string;
                        setReasoningEffort(v === "__auto__" ? null : v);
                        setDirty(true);
                      }}
                      options={[
                        {
                          label: t("models.switchToAuto"),
                          value: "__auto__",
                        },
                        ...(
                          reasoningEffortOptions ?? [
                            "none",
                            "minimal",
                            "low",
                            "medium",
                            "high",
                            "xhigh",
                          ]
                        ).map((v) => ({
                          label: v.charAt(0).toUpperCase() + v.slice(1),
                          value: v,
                        })),
                      ]}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
      {/* Responses API models handle reasoning via native reasoning items
         that the API requires to be echoed back; relay_reasoning has no
         effect, so hide the toggle to avoid confusion. */}
      {!compact && chatModel !== "OpenAIResponseModel" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 8,
            padding: "6px 0",
          }}
        >
          <div>
            <span
              style={{
                fontSize: 13,
                color: isDark ? "rgba(255,255,255,0.85)" : "#333",
              }}
            >
              {t("models.relayReasoningLabel")}
            </span>
            <div
              style={{
                fontSize: 11,
                color: isDark ? "rgba(255,255,255,0.35)" : "#999",
                marginTop: 2,
              }}
            >
              {t("models.relayReasoningHint")}
            </div>
          </div>
          <Switch
            checked={relayReasoning}
            onChange={(checked) => {
              setRelayReasoning(checked);
              setDirty(true);
            }}
          />
        </div>
      )}

      {!compact && (
        <>
          <div
            style={{
              fontSize: 12,
              color: isDark ? "rgba(255,255,255,0.45)" : "#888",
              marginBottom: 4,
            }}
          >
            {t("models.modelGenerateConfigHint")}
          </div>
          <JsonConfigEditor
            value={text}
            onChange={handleChange}
            placeholder={`Example:\n{\n  "extra_body": {\n    "enable_thinking": false\n  }\n}`}
          />
        </>
      )}
      {/* 精简模式选择即存，无需保存按钮；完整模式保留显式保存 */}
      {!compact && (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginTop: 8,
            gap: 8,
          }}
        >
          <Button
            type="primary"
            size="small"
            loading={saving}
            disabled={!dirty}
            onClick={handleSave}
          >
            {t("models.save")}
          </Button>
        </div>
      )}
    </div>
  );
}
