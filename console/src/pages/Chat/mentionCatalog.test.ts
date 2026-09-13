import { afterEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";

import {
  buildMentionItems,
  classifyMentionToken,
  clearMentionCache,
  getCachedSkillNames,
  isMentionPopoverOpen,
  normalizeMentionTokens,
  normalizeUserMessageMentions,
} from "./mentionCatalog";

const listSkills = vi.fn();
const listTools = vi.fn();
const listMCPClients = vi.fn();
const loadFileText = vi.fn();

vi.mock("../../api/modules/skill", () => ({
  skillApi: {
    get listSkills() {
      return listSkills;
    },
  },
}));
vi.mock("../../api/modules/tools", () => ({
  toolsApi: {
    get listTools() {
      return listTools;
    },
  },
}));
vi.mock("../../api/modules/mcp", () => ({
  mcpApi: {
    get listMCPClients() {
      return listMCPClients;
    },
  },
}));
vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    get loadFileText() {
      return loadFileText;
    },
  },
}));

const t = ((key: string, fallback?: string) => fallback ?? key) as unknown as TFunction;

function mockSources(): void {
  loadFileText.mockImplementation(async (name: string) => ({
    content: name === "SOUL.md" ? "" : `content of ${name}`,
  }));
  listSkills.mockResolvedValue([
    {
      name: "docx",
      description: "Word 文档处理",
      emoji: "📄",
      enabled: true,
    },
    { name: "ghost", description: "未启用技能", emoji: "", enabled: false },
  ]);
  listTools.mockResolvedValue([
    { name: "web_search", description: "网页搜索", enabled: true },
  ]);
  listMCPClients.mockResolvedValue([
    {
      key: "feishu",
      name: "飞书",
      description: "飞书开放平台",
      enabled: true,
    },
  ]);
}

afterEach(() => {
  vi.clearAllMocks();
  clearMentionCache();
});

describe("buildMentionItems", () => {
  it("assembles groups in order with enabled-only filtering", async () => {
    mockSources();
    const items = await buildMentionItems("bot", t);

    // 档案（存在的）→ 技能（仅启用）→ 工具 → MCP
    expect(items.map((item) => item.value)).toEqual([
      "PROFILE.md",
      "AGENTS.md",
      "agent.json",
      "docx",
      "web_search",
      "feishu",
    ]);
    expect(items[0]?.type).toBe("档案");
    expect(items[3]?.type).toBe("技能");
    expect(items[3]?.label).toContain("📄 docx");
    expect(items[5]?.type).toBe("MCP");
    // 分组标题文本随 item 下发，由 SDK 弹层补丁渲染为组首标题行
    expect(items[0]?.group).toBe("档案");
    expect(items[3]?.group).toBe("技能");
    expect(items[4]?.group).toBe("工具");
    expect(items[5]?.group).toBe("MCP");
    // 分类图标供弹层候选与 header 胶囊渲染
    expect(items[0]?.icon).toBeTruthy();
    expect(items[3]?.icon).toBeTruthy();
  });

  it("caches per agent within the TTL window", async () => {
    mockSources();
    await buildMentionItems("bot", t);
    await buildMentionItems("bot", t);

    expect(listSkills).toHaveBeenCalledTimes(1);

    // 另一个 agent 不共享缓存
    await buildMentionItems("other", t);
    expect(listSkills).toHaveBeenCalledTimes(2);
  });

  it("keeps remaining groups when one source fails", async () => {
    mockSources();
    listSkills.mockRejectedValue(new Error("skills 404"));
    const items = await buildMentionItems("bot", t);

    expect(items.map((item) => item.value)).toEqual([
      "PROFILE.md",
      "AGENTS.md",
      "agent.json",
      "web_search",
      "feishu",
    ]);
  });
});

describe("normalizeMentionTokens", () => {
  it("rewrites cached skill tokens to slash commands", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    // 菜单插入形态：@值 无空格、已在句首 → 直接转斜杠命令
    expect(normalizeMentionTokens("@docx 帮我处理文档", "bot")).toBe(
      "/docx 帮我处理文档",
    );
    // 值内携带斜杠前缀的形态同样归一
    expect(normalizeMentionTokens("@/docx 帮我", "bot")).toBe("/docx 帮我");
  });

  it("moves mid-sentence skill tokens to the front", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    // 后端只认句首斜杠命令：句中 token 移出原位并前置，残留双空格折叠
    expect(normalizeMentionTokens("帮我处理 @docx 这份文档", "bot")).toBe(
      "/docx 帮我处理 这份文档",
    );
    // CJK 紧跟 @ 的中文输入法场景同样命中
    expect(normalizeMentionTokens("用@docx处理", "bot")).toBe(
      "/docx 用处理",
    );
  });

  it("adds the protocol space for file/tool/mcp tokens", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    expect(normalizeMentionTokens("@PROFILE.md 你好", "bot")).toBe(
      "@ PROFILE.md 你好",
    );
    expect(normalizeMentionTokens("@web_search 查一下", "bot")).toBe(
      "@ web_search 查一下",
    );
    expect(normalizeMentionTokens("@feishu 发消息", "bot")).toBe(
      "@ feishu 发消息",
    );
  });

  it("truncates glued Chinese punctuation after identity docs", () => {
    // 静态白名单前缀匹配，不依赖候选缓存（SOUL.md 未加载过也能截断）
    expect(normalizeMentionTokens("@SOUL.md，帮我改改", "bot")).toBe(
      "@ SOUL.md，帮我改改",
    );
  });

  it("leaves emails, spaced refs and plain text untouched", () => {
    expect(normalizeMentionTokens("联系 a@b.com 确认", "bot")).toBe(
      "联系 a@b.com 确认",
    );
    // 预填/手打的带空格协议已是最终形态
    expect(normalizeMentionTokens("@ PROFILE.md 帮我修改", "bot")).toBe(
      "@ PROFILE.md 帮我修改",
    );
    expect(normalizeMentionTokens("普通文本，无 @ 符号", "bot")).toBe(
      "普通文本，无 @ 符号",
    );
  });

  it("degrades unknown tokens when the catalog cache is cold", () => {
    // 从未加载过候选（无持久副本）：技能 token 退化为普通 @ 引用，不丢文本
    expect(getCachedSkillNames("cold").size).toBe(0);
    expect(normalizeMentionTokens("@docx 帮我", "cold")).toBe("@ docx 帮我");
  });

  it("keeps skill tokens working after the TTL expires", async () => {
    // 回归：SDK cacheItems 弹层重开不回调 items()，TTL 过期后
    // 技能名单必须仍可用（持久副本），不得静默降级成 @ 引用
    vi.useFakeTimers();
    try {
      mockSources();
      await buildMentionItems("bot", t);
      vi.advanceTimersByTime(31_000);

      expect(normalizeMentionTokens("@docx 帮我", "bot")).toBe("/docx 帮我");
    } finally {
      vi.useRealTimers();
    }
  });

  it("normalizes multiple mentions in insertion order", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    // 技能前置句首，档案引用原位补协议空格
    expect(
      normalizeMentionTokens("@docx @PROFILE.md 帮我一起处理", "bot"),
    ).toBe("/docx @ PROFILE.md 帮我一起处理");
  });
});

describe("classifyMentionToken", () => {
  it("classifies slash/skill/file/ref tokens for chip icons", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    // 斜杠命令与命中技能名单的 @ token 都算技能（闪电图标）
    expect(classifyMentionToken("/pdf", "bot")).toBe("skill");
    expect(classifyMentionToken("@docx", "bot")).toBe("skill");
    // 档案白名单文件（文档图标），带空格协议形态同样命中
    expect(classifyMentionToken("@PROFILE.md", "bot")).toBe("file");
    expect(classifyMentionToken("@ SOUL.md", "bot")).toBe("file");
    // 其余 @ token（工具/MCP/未知）走通用引用
    expect(classifyMentionToken("@web_search", "bot")).toBe("ref");
    expect(classifyMentionToken("@ghost", "bot")).toBe("ref");
  });
});

describe("normalizeUserMessageMentions", () => {
  it("rewrites string content and keeps other fields", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    const next = normalizeUserMessageMentions(
      { role: "user", content: "@docx 帮我", foo: 1 },
      "bot",
    );
    expect(next.content).toBe("/docx 帮我");
    expect(next.role).toBe("user");
    expect(next.foo).toBe(1);
  });

  it("rewrites only text parts of multimodal content arrays", async () => {
    mockSources();
    await buildMentionItems("bot", t);

    const next = normalizeUserMessageMentions(
      {
        role: "user",
        content: [
          { type: "text", text: "@PROFILE.md 看这个" },
          { type: "image_url", image_url: { url: "https://x/y.png" } },
        ],
      },
      "bot",
    );
    const parts = next.content as Array<Record<string, unknown>>;
    expect(parts[0]).toEqual({ type: "text", text: "@ PROFILE.md 看这个" });
    // 非文本分片原样透传
    expect(parts[1]).toEqual({
      type: "image_url",
      image_url: { url: "https://x/y.png" },
    });
  });

  it("returns the message unchanged when content is absent", () => {
    const msg = { role: "user" };
    expect(normalizeUserMessageMentions(msg, "bot")).toBe(msg);
  });
});

describe("isMentionPopoverOpen", () => {
  it("returns false when no popover exists", () => {
    expect(isMentionPopoverOpen()).toBe(false);
  });

  it("returns true when a visible mention popover exists", () => {
    const popover = document.createElement("div");
    popover.className = "qwenpaw-chat-anywhere-input-mentions-popover";
    document.body.appendChild(popover);
    try {
      expect(isMentionPopoverOpen()).toBe(true);
    } finally {
      popover.remove();
    }
  });
});
