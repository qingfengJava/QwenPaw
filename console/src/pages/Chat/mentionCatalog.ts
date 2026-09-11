/**
 * mentionCatalog.ts — 聊天输入框 @ 提及菜单的候选项目录。
 *
 * 数据源（分类级独立降级，单类失败不阻塞其余分类）：
 * - 档案：工作区根白名单文件（逐个探测，仅存在的进入候选）；
 * - 技能：skillApi（仅启用项，与运行时渐进加载范围一致）；
 * - 工具：toolsApi（仅启用项）；
 * - MCP：mcpApi（仅启用客户端）。
 *
 * 选中行为（SDK inline 模式 + 镜像层胶囊，对标竞品内联实体）：候选
 * 以 `@值` 插入光标处，由 mentionChipOverlay 渲染为嵌在文字流中的
 * 胶囊（图标 + × 整 token 删除）。发送前由 normalizeMentionTokens 把
 * token 规范化为后端既有协议：
 * - 技能 → `/技能名` 并移到句首（后端 _parse_skill_query 要求斜杠命令
 *   位于句首，且一条消息只解析第一个斜杠命令；原位 token 删除）；
 * - 档案/工具/MCP → `@ 名称`（`@` 后空格是 fileReferenceFormatting
 *   解析协议的一部分，消息可点击预览、agent 可读文件），原位保留。
 *
 * 结果按 agentId 做 30s TTL 缓存：SDK 侧 cacheItems 只在弹层会话内生效，
 * 这里兜住弹层反复打开带来的高频拉取；normalizeMentionTokens 复用
 * 同一缓存识别技能名，不触发额外请求。
 */

import {
  ApiOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { jsx as _jsx } from "react/jsx-runtime";
import type { ReactNode } from "react";
import type { TFunction } from "i18next";
import { skillApi } from "../../api/modules/skill";
import { toolsApi } from "../../api/modules/tools";
import { mcpApi } from "../../api/modules/mcp";
import { workspaceApi } from "../../api/modules/workspace";
import { IDENTITY_DOC_FILES } from "../Agents/identityDocFiles";

/** SDK IAgentScopeRuntimeWebUISenderMentionItem 的结构兼容子集。 */
export interface MentionItem {
  /** 选中后参与序列化的值（文件名 / 技能名 / 工具名 / MCP key）。 */
  value: string;
  /** 弹层候选与 capsule 展示文本（名称 + 截断描述）。 */
  label?: string;
  /** 弹层右侧的分类徽标文本（本地化）。 */
  type?: string;
  /** 弹层候选与 header 胶囊展示的分类图标。 */
  icon?: ReactNode;
  /**
   * 内部分类标记（协议规范化依赖）。SDK 类型不含此字段，
   * 结构类型下向后兼容，运行时随对象原样透传。
   */
  mentionKind?: "file" | "skill" | "tool" | "mcp";
}

/** 单候选描述文本的最大长度（超出截断，避免弹层过宽）。 */
const LABEL_DESC_MAX = 40;

const CACHE_TTL_MS = 30_000;
const cache = new Map<string, { items: MentionItem[]; at: number }>();

/**
 * 技能名持久副本（agentId → 启用技能名集合）。
 *
 * 不能跟着 30s TTL 走：SDK 的 cacheItems 在弹层重开时不会回调 items()，
 * 若只存 TTL 缓存，过期后发送链路的 normalizeMentionTokens 拿不到技能
 * 名单，会把技能胶囊静默降级成普通 `@ 名字` 引用（刚选的技能隔一会儿
 * 再发就变味）。此副本只随 buildMentionItems 成功拉取而刷新、永不过期：
 * 最坏情况是名单略旧（刚删的技能误转斜杠→后端本就不加载；刚加的
 * 技能短暂降级 @ 引用），远优于名单为空。
 */
const skillNamesByAgent = new Map<string, Set<string>>();

function readCache(agentId: string): MentionItem[] | null {
  const hit = cache.get(agentId);
  if (!hit) return null;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    cache.delete(agentId);
    return null;
  }
  return hit.items;
}

/** 主动失效候选缓存（技能/工具/MCP 变更后可调用；测试用）。 */
export function clearMentionCache(): void {
  cache.clear();
  skillNamesByAgent.clear();
}

/** 名称 + 截断描述组合成候选展示文本。 */
function compactLabel(
  name: string,
  description?: string,
  emoji?: string,
): string {
  const prefix = emoji ? `${emoji} ${name}` : name;
  const desc = description?.trim();
  if (!desc) return prefix;
  const short =
    desc.length > LABEL_DESC_MAX ? `${desc.slice(0, LABEL_DESC_MAX)}…` : desc;
  return `${prefix} · ${short}`;
}

/** 并发探测白名单档案文件，仅存在的进入候选（与档案 Tab 探测规则一致）。 */
async function fetchIdentityDocValues(): Promise<string[]> {
  const results = await Promise.allSettled(
    IDENTITY_DOC_FILES.map(async (name) => ({
      name,
      content: (await workspaceApi.loadFileText(name, undefined, "workspace"))
        .content,
    })),
  );
  const values: string[] = [];
  for (const result of results) {
    if (result.status !== "fulfilled") continue;
    if (!result.value.content.trim()) continue;
    values.push(result.value.name);
  }
  return values;
}

/**
 * 组装 @ 提及候选：档案 → 技能 → 工具 → MCP。
 *
 * 单类失败静默置空（Promise.allSettled + 逐类守卫），其余分类照常展示。
 */
export async function buildMentionItems(
  agentId: string,
  t: TFunction,
): Promise<MentionItem[]> {
  const cached = readCache(agentId);
  if (cached) return cached;

  const [files, skills, tools, mcps] = await Promise.allSettled([
    fetchIdentityDocValues(),
    skillApi.listSkills(agentId),
    toolsApi.listTools(),
    mcpApi.listMCPClients(),
  ]);

  const typeFile = t("chat.mentionGroupFile", "档案");
  const typeSkill = t("chat.mentionGroupSkill", "技能");
  const typeTool = t("chat.mentionGroupTool", "工具");

  const items: MentionItem[] = [];

  if (files.status === "fulfilled") {
    for (const value of files.value) {
      items.push({
        value,
        label: value,
        type: typeFile,
        icon: _jsx(FileTextOutlined, {}),
        mentionKind: "file",
      });
    }
  }
  if (skills.status === "fulfilled") {
    // 技能名单写入持久副本：发送链路规范化不依赖 TTL 新鲜度
    skillNamesByAgent.set(
      agentId,
      new Set(skills.value.filter((skill) => skill.enabled).map((skill) => skill.name)),
    );
    for (const skill of skills.value) {
      // 与运行时一致：未启用的技能不会被渐进加载，不进候选
      if (!skill.enabled) continue;
      items.push({
        value: skill.name,
        label: compactLabel(skill.name, skill.description, skill.emoji),
        type: typeSkill,
        icon: _jsx(ThunderboltOutlined, {}),
        mentionKind: "skill",
      });
    }
  }
  if (tools.status === "fulfilled") {
    for (const tool of tools.value) {
      if (!tool.enabled) continue;
      items.push({
        value: tool.name,
        label: compactLabel(tool.name, tool.description),
        type: typeTool,
        icon: _jsx(ToolOutlined, {}),
        mentionKind: "tool",
      });
    }
  }
  if (mcps.status === "fulfilled") {
    for (const client of mcps.value) {
      if (!client.enabled) continue;
      items.push({
        value: client.key,
        label: compactLabel(client.name || client.key, client.description),
        type: "MCP",
        icon: _jsx(ApiOutlined, {}),
        mentionKind: "mcp",
      });
    }
  }

  cache.set(agentId, { items, at: Date.now() });
  return items;
}

/**
 * 当前 agent 的启用技能名集合（取自持久副本，无记录返回空集合）。
 *
 * 供发送前协议规范化与胶囊镜像层识别「@ 技能名」使用；副本在首次
 * 弹层候选加载时建立、不随 TTL 过期，避免发送链路触发额外请求也避免
 * 静默降级。
 */
export function getCachedSkillNames(agentId?: string): Set<string> {
  if (!agentId) return new Set();
  return skillNamesByAgent.get(agentId) ?? new Set();
}

/**
 * 胶囊 token 分类（决定镜像层胶囊图标）：输入为 chip 原文
 * （`@docx` / `@ PROFILE.md` / `/pdf`），技能名单取自当前 agent 目录。
 *
 * 供 mentionChipOverlay 的 setChipClassifier 注入，与发送链路共用
 * 同一份技能持久副本，保证「看到的图标」与「发送后的协议」一致。
 */
export function classifyMentionToken(
  token: string,
  agentId?: string,
): "file" | "skill" | "ref" {
  if (token.startsWith("/")) {
    return "skill";
  }
  const name = token.replace(/^@\s?/, "");
  if (getCachedSkillNames(agentId).has(name)) {
    return "skill";
  }
  if ((IDENTITY_DOC_FILES as readonly string[]).includes(name)) {
    return "file";
  }
  return "ref";
}

/**
 * 把输入框内的 mention token 规范化为后端既有协议。
 *
 * token 形态：`@值`（菜单插入/手打无空格）、`@ 值`（预填/手打带空格，
 * 已是文件协议最终形态）、`/值`（手打斜杠命令，原位不动）；@ 前允许
 * CJK 字符（中文输入法后直接接 @ 是高频场景），token 字符集限 ASCII
 * 词符（与镜像层切分一致，中文标点/汉字粘连处天然截断、余文原位保留）。
 *
 * 规则（按序命中）：
 * - `@/名字` 或 `@名字` 且名字 ∈ 技能目录 → 从原位删除，`/名字` 统一
 *   前置到句首（后端只认句首斜杠命令且仅解析第一个；多个技能全部
 *   前置，后端按首个解析）；
 * - `@档案名` → `@ 档案名`（`@` 后空格是 fileReferenceFormatting 协议的
 *   一部分）；
 * - 其余（工具/MCP）→ `@ 值`，原位保留。
 *
 * 邮箱（@ 前是 ASCII 字母）不匹配、原样保留；未命中技能名单的 token
 * 退化为普通 `@ 名字` 引用，不丢文本。
 */
export function normalizeMentionTokens(text: string, agentId?: string): string {
  if (!text.includes("@")) return text;
  const skills = getCachedSkillNames(agentId);
  const skillTokens: string[] = [];
  const normalized = text.replace(
    /(^|\s|\P{ASCII})@([\w.\\/:+-]+)/gu,
    (_raw, lead: string, token: string) => {
      const name = token.startsWith("/") ? token.slice(1) : token;
      if (skills.has(name)) {
        // 技能 token 移出原位，稍后统一前置句首；lead（CJK/空白）保留
        skillTokens.push(name);
        return lead;
      }
      if ((IDENTITY_DOC_FILES as readonly string[]).includes(name)) {
        return `${lead}@ ${name}`;
      }
      return `${lead}@ ${token}`;
    },
  );
  if (skillTokens.length === 0) {
    return normalized;
  }
  // token 移除后原位可能残留双空格：折叠空格并去句首空白后再前置
  const rest = normalized.replace(/[ \t]{2,}/g, " ").replace(/^ +/, "");
  return `${skillTokens.map((name) => `/${name}`).join(" ")} ${rest}`;
}

/**
 * 对一条用户消息做提及协议规范化。
 *
 * content 兼容 string 与多模态数组两种形态：string 直接改写；数组仅
 * 改写 type === "text" 的分片，图片/文件分片原样透传。返回新对象，
 * 不修改入参。供 customFetch 在消息发往后端前调用（输入框内的
 * `@值`/`@ 值` token → 既有 `@ 名字` / 句首 `/名字` 协议）。
 */
export function normalizeUserMessageMentions(
  msg: Record<string, unknown>,
  agentId?: string,
): Record<string, unknown> {
  const content = msg.content;
  if (typeof content === "string") {
    return { ...msg, content: normalizeMentionTokens(content, agentId) };
  }
  if (Array.isArray(content)) {
    return {
      ...msg,
      content: content.map((part) => {
        if (
          !part ||
          typeof part !== "object" ||
          (part as { type?: unknown }).type !== "text" ||
          typeof (part as { text?: unknown }).text !== "string"
        ) {
          return part;
        }
        return {
          ...part,
          text: normalizeMentionTokens(
            (part as { text: string }).text,
            agentId,
          ),
        };
      }),
    };
  }
  return msg;
}

/**
 * SDK mention 弹层（antd Popover）当前是否打开。
 *
 * SDK 的 rootClassName 固定带 `...-chat-anywhere-input-mentions-popover`
 * 后缀（prefixCls 随全局 antd 前缀变化），用包含匹配兼容任意前缀；
 * 弹层配置 destroyOnHidden: true，关闭即从 DOM 卸载，故存在即开启。
 * 供消息历史导航（document 级捕获监听）让位：弹层开启时方向键属于
 * 候选导航，禁止替换输入框内容。
 */
export function isMentionPopoverOpen(): boolean {
  return (
    !!document.querySelector(
      '[class*="chat-anywhere-input-mentions-popover"]',
    )
  );
}
