import { describe, it, expect } from "vitest";
import { listSelectableModels } from "./selectableModels";
import type { ProviderInfo } from "../api/types";

function makeModel(id: string): ProviderInfo["models"][number] {
  return {
    id,
    name: id,
    supports_multimodal: false,
    supports_image: false,
    supports_video: false,
    max_output_length: 4096,
    max_input_length: 32768,
    generate_kwargs: {},
    relay_reasoning: false,
    thinking_enabled: null,
    thinking_budget: null,
    reasoning_effort: null,
  };
}

function makeProvider(overrides: Partial<ProviderInfo>): ProviderInfo {
  return {
    id: "test-provider",
    name: "Test Provider",
    api_key_prefix: "test",
    chat_model: "test-model",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    support_model_discovery: false,
    support_connection_check: false,
    freeze_url: false,
    require_api_key: true,
    api_key: "sk-test",
    base_url: "https://api.test.com",
    generate_kwargs: {},
    ...overrides,
  };
}

describe("listSelectableModels（禁用模型从选择器隐藏）", () => {
  it("未配置 disabled_model_ids 时返回 models + extra_models 全量合并", () => {
    const provider = makeProvider({
      models: [makeModel("model-1")],
      extra_models: [makeModel("model-2")],
    });

    const result = listSelectableModels(provider);

    expect(result.map((m) => m.id)).toEqual(["model-1", "model-2"]);
  });

  it("剔除 disabled_model_ids 中的模型，models 与 extra_models 一视同仁", () => {
    const provider = makeProvider({
      models: [makeModel("qwen3.8-max"), makeModel("qwen3.8-flash")],
      extra_models: [makeModel("user-added")],
      disabled_model_ids: ["qwen3.8-max", "user-added"],
    });

    const result = listSelectableModels(provider);

    expect(result.map((m) => m.id)).toEqual(["qwen3.8-flash"]);
  });

  it("disabled_model_ids 为 undefined 或空数组时不剔除任何模型", () => {
    const provider = makeProvider({
      models: [makeModel("model-1")],
      extra_models: [makeModel("model-2")],
    });

    expect(listSelectableModels(provider)).toHaveLength(2);
    expect(listSelectableModels({ ...provider, disabled_model_ids: [] }))
      .toHaveLength(2);
  });

  it("全部模型被禁用时返回空数组", () => {
    const provider = makeProvider({
      models: [makeModel("model-1")],
      extra_models: [makeModel("model-2")],
      disabled_model_ids: ["model-1", "model-2"],
    });

    expect(listSelectableModels(provider)).toHaveLength(0);
  });
});
