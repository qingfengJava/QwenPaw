/**
 * AgentModelSelector.test.tsx — 员工默认模型选择器组件测试。
 *
 * 覆盖：未配置时跟随全局默认（徽标）、已配置显示配置值、
 * 选择即写 agent 级默认模型（scope=agent）并提示成功。
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test/common_setup";
import AgentModelSelector from "./AgentModelSelector";

const { mockMessage } = vi.hoisted(() => ({
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
    setActiveLlm: vi.fn(),
  },
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

import { providerApi } from "@/api/modules/provider";

const providerFixture = {
  id: "aliyun-codingplan",
  name: "Aliyun",
  api_key: "sk-test",
  base_url: "https://example.com",
  chat_model: "OpenAIChatModel",
  models: [
    { id: "GLM-5.3-Flash", name: "GLM-5.3-Flash", is_free: false },
    { id: "qwen-max", name: "Qwen Max", is_free: false },
  ],
  extra_models: [],
  disabled_model_ids: [],
  is_custom: false,
  is_local: false,
  require_api_key: true,
  support_model_discovery: false,
  support_connection_check: false,
  freeze_url: false,
} as never;

function mockActive(scope: "agent" | "effective", active_llm: unknown) {
  return { active_llm, effective_max_input_length: null };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(providerApi.listProviders).mockResolvedValue([providerFixture]);
  vi.mocked(providerApi.getActiveModels).mockImplementation(async (params) =>
    mockActive(
      params?.scope ?? "effective",
      params?.scope === "agent"
        ? null
        : { provider_id: "global-provider", model: "global-model" },
    ),
  );
  vi.mocked(providerApi.setActiveLlm).mockResolvedValue({
    active_llm: { provider_id: "aliyun-codingplan", model: "GLM-5.3-Flash" },
    effective_max_input_length: null,
  });
});

describe("AgentModelSelector", () => {
  it("shows the effective model with a follow-global tag when unconfigured", async () => {
    const { getByTitle } = renderWithProviders(
      <AgentModelSelector agentId="default" />,
    );

    // 未配置：pill 回退显示生效值（全局默认）并附跟随徽标
    await waitFor(() => {
      expect(getByTitle(/跟随全局默认/)).toBeTruthy();
    });
  });

  it("shows the agent-specific model without the tag when configured", async () => {
    vi.mocked(providerApi.getActiveModels).mockImplementation(async (params) =>
      mockActive(
        params?.scope ?? "effective",
        params?.scope === "agent"
          ? { provider_id: "aliyun-codingplan", model: "GLM-5.3-Flash" }
          : { provider_id: "aliyun-codingplan", model: "GLM-5.3-Flash" },
      ),
    );

    const { getByTitle, queryByTitle } = renderWithProviders(
      <AgentModelSelector agentId="default" />,
    );

    // 已配置：显示配置值，不出现跟随徽标
    await waitFor(() => {
      expect(getByTitle("GLM-5.3-Flash")).toBeTruthy();
    });
    expect(queryByTitle(/跟随全局默认/)).toBeNull();
  });

  it("writes scope=agent default model on selection and toasts success", async () => {
    const { getByTitle, findByText } = renderWithProviders(
      <AgentModelSelector agentId="default" />,
    );

    // 等待数据就绪后展开下拉
    await waitFor(() => {
      expect(getByTitle(/配置该员工后台默认运行的模型/)).toBeTruthy();
    });
    fireEvent.click(getByTitle(/配置该员工后台默认运行的模型/));

    // 选择菜单项（按 provider 分组）
    const item = await findByText("GLM-5.3-Flash");
    fireEvent.click(item);

    await waitFor(() => {
      expect(providerApi.setActiveLlm).toHaveBeenCalledWith({
        provider_id: "aliyun-codingplan",
        model: "GLM-5.3-Flash",
        scope: "agent",
        agent_id: "default",
      });
    });
    await waitFor(() => {
      expect(mockMessage.success).toHaveBeenCalled();
    });
  });

  it("toasts an error when saving fails", async () => {
    vi.mocked(providerApi.setActiveLlm).mockRejectedValue(
      new Error("network down"),
    );

    const { getByTitle, findByText } = renderWithProviders(
      <AgentModelSelector agentId="default" />,
    );

    await waitFor(() => {
      expect(getByTitle(/配置该员工后台默认运行的模型/)).toBeTruthy();
    });
    fireEvent.click(getByTitle(/配置该员工后台默认运行的模型/));
    fireEvent.click(await findByText("GLM-5.3-Flash"));

    await waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalled();
    });
  });
});
