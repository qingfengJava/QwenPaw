import type { ModelInfo } from "../api/types";

/** 选择器过滤所需的最小 provider 结构（ProviderInfo 的结构子集）。 */
export interface SelectableModelsSource {
  models?: ModelInfo[];
  extra_models?: ModelInfo[];
  disabled_model_ids?: string[];
}

/**
 * 返回可在模型选择器中展示的模型列表。
 *
 * 合并 models 与 extra_models 后剔除 disabled_model_ids 中的模型，
 * 对齐后端 Provider.configured_models 的过滤契约：禁用模型保留配置，
 * 但在重新启用前从所有选择器隐藏（模型管理弹窗的启用/禁用开关）。
 */
export function listSelectableModels(
  provider: SelectableModelsSource,
): ModelInfo[] {
  // 禁用清单缺省或为空时表示"无禁用"，不做任何剔除
  const disabled = new Set(provider.disabled_model_ids ?? []);

  // 合并内置与用户添加模型，统一剔除禁用项
  return [...(provider.models ?? []), ...(provider.extra_models ?? [])].filter(
    (model) => !disabled.has(model.id),
  );
}
