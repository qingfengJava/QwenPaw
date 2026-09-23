/**
 * openAgentWorkbench — 在新浏览器标签页打开数字员工工作台（/studio/:aid）。
 *
 * - 浏览器端：window.open(_blank)，深链可刷新，auth token 存
 *   localStorage，新标签页天然共享登录态；
 * - Tauri 桌面端：window.open(_blank) 会被拦截到系统浏览器
 *   （见 App.tsx 的 interceptBlankLinkClicks），降级为当前标签内跳转。
 */
import { addRouterBasename } from "./navigationMode";
import { isDesktopTauriRuntime } from "./openExternalLink";

/** 工作台应用内路径（router basename 由本模块按当前地址拼接）。 */
export function buildWorkbenchPath(agentId: string): string {
  return `/studio/${encodeURIComponent(agentId)}`;
}

/** 新标签页打开工作台；桌面端降级为当前标签内跳转。 */
export function openAgentWorkbench(agentId: string): void {
  const target = addRouterBasename(
    window.location.pathname,
    buildWorkbenchPath(agentId),
  );
  if (isDesktopTauriRuntime()) {
    window.location.assign(target);
    return;
  }
  window.open(target, "_blank", "noopener");
}
