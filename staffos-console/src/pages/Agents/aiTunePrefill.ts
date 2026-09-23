/**
 * aiTunePrefill.ts — 「AI 调优」预填指令的一次性传递。
 *
 * 员工档案栏/概览页的快捷指令点击后 stash，Chat 挂载后 take 消费并
 * 预填输入框。走 sessionStorage 而非路由 state：避免改动 Chat 公共
 * props 契约，且跨 Tab 导航（/agents/:aid → /agents/:aid/chat）不丢。
 */

const KEY = "qwenpaw.aiTune.prefill";

/** 记录待预填指令（后写覆盖先写）。 */
export function stashAiTunePrompt(text: string): void {
  try {
    sessionStorage.setItem(KEY, text);
  } catch {
    // 存储不可用时静默：仅损失预填体验。
  }
}

/** 取出并清除待预填指令；无则返回 null。 */
export function takeAiTunePrompt(): string | null {
  try {
    const value = sessionStorage.getItem(KEY);
    if (value !== null) {
      sessionStorage.removeItem(KEY);
    }
    return value;
  } catch {
    return null;
  }
}
