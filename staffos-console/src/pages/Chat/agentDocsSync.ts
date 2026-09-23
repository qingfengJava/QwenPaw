/**
 * agentDocsSync.ts — 「对话修改」闭环的轮次收尾处理。
 *
 * AI 运行时的文件编辑工具直改工作区档案文件，不经过 workspace 写
 * 端点（该路径没有影子写）。因此当本轮用户消息引用了白名单档案
 * 文件时，在 SSE 流结束（flush）后：先调用 sync-from-files 把文件
 * 回填 PG 权威行（档案 Tab 读路径 PG 优先，必须先落库再刷新），
 * 再广播 agent-docs-changed 让档案 Tab 静默刷新展示。
 */

import { agentsApi } from "../../api/modules/agents";
import {
  IDENTITY_DOC_FILES,
  type IdentityDocFile,
} from "../Agents/identityDocFiles";
import { splitFileReferences } from "./fileReferenceFormatting";

/** 档案文档变更广播事件（聊天流结束 → 档案 Tab 刷新）。 */
export const AGENT_DOCS_CHANGED_EVENT = "qwenpaw:agent-docs-changed";

/**
 * 广播档案文档变更。
 *
 * 事件不携带 agentId：workspace 读路径跟随 selectedAgent 借壳（工作台
 * 调试态自动指向草稿工作区），监听方按各自当前数据域重新拉取即可。
 */
export function dispatchAgentDocsChanged(): void {
  window.dispatchEvent(new CustomEvent(AGENT_DOCS_CHANGED_EVENT));
}

/**
 * 提取本轮用户文本引用的白名单档案文件名（去重、保序）。
 *
 * 中文输入习惯常把标点紧贴文件名（如「@ SOUL.md，帮我…」），
 * 引用解析会把后续非空白字符一并吞进 path，故这里对 basename 做
 * 白名单前缀匹配而非全等匹配。
 */
export function extractIdentityDocRefs(text: string): IdentityDocFile[] {
  const hit = new Set<IdentityDocFile>();
  for (const segment of splitFileReferences(text)) {
    if (segment.reference?.kind !== "file") continue;
    const name = segment.reference.path.split(/[\\/]/).pop() ?? "";
    const matched = IDENTITY_DOC_FILES.find(
      (file) => name === file || name.startsWith(file),
    );
    if (matched) {
      hit.add(matched);
    }
  }
  return [...hit];
}

/**
 * 包装聊天响应流：轮次结束后回填 PG 并广播刷新。
 *
 * 仅当本轮用户文本命中档案文件引用时生效（其余轮次原样返回，避免
 * 每轮无谓 IO）；同步失败只告警——聊天主链路绝不因回填失败中断。
 */
export function wrapResponseForDocSync(
  response: Response,
  agentId: string,
  userText: string,
): Response {
  if (!response.ok || !response.body) return response;
  if (extractIdentityDocRefs(userText).length === 0) return response;

  const transformed = response.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      flush() {
        void (async () => {
          try {
            // 先落 PG（读路径 PG 优先），完成后再广播刷新
            await agentsApi.syncDocumentsFromFiles(agentId);
          } catch (err) {
            console.warn("[agentDocsSync] sync-from-files failed:", err);
          }
          dispatchAgentDocsChanged();
        })();
      },
    }),
  );
  return new Response(transformed, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
