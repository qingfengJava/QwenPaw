/**
 * 运行日志「列表 ↔ 详情」的路径派生工具。
 *
 * 这两个页面（RunLogs/index.tsx、RunLogDetailPage.tsx）被两套壳复用：
 *   - AgentDetailLayout（/agents/:aid/*）：右栏是真正的嵌套 <Routes>，
 *     子页面有 route 匹配上下文，useParams / 相对导航都可用；
 *   - AgentWorkbenchLayout（/studio/:aid 沙箱）：右栏改为按 pathname 条件
 *     渲染（见该文件顶部说明），**没有 <Route> 匹配**。此时 useParams 返回
 *     空对象，且相对导航（"runs/:id"、"../sessions"）会以 "/" 为基准解析，
 *     越界命中沙箱 CatchAllNavigate 兜底 → 弹回档案页（表现为“点击不跳转”）。
 *
 * 因此这里统一用「当前 pathname 派生绝对路径」的方式做导航与取参，保证两套壳
 * 行为一致：绝对路径不依赖 route 匹配上下文，在有无 <Routes> 时都成立。
 */

/**
 * 由会话列表页 pathname（形如 …/sessions）派生运行日志详情页绝对路径。
 *
 * @param sessionsPathname 列表页当前 pathname（…/:aid/sessions）
 * @param runId            目标运行日志 id
 * @returns 详情页绝对路径 …/:aid/sessions/runs/:runId
 */
export function buildRunDetailPath(
  sessionsPathname: string,
  runId: string,
): string {
  // 去掉可能的尾斜杠后拼接，避免出现 "//runs"。
  const base = sessionsPathname.replace(/\/+$/, "");
  return `${base}/runs/${runId}`;
}

/**
 * 由详情页 pathname（…/:aid/sessions/runs/:runId）解析 aid 与 runId。
 *
 * 用于工作台沙箱内 useParams 为空时的兜底取参。正则匹配紧邻 "/sessions/runs/"
 * 之前的那一段作为 aid，天然兼容 /studio 与 /agents 两种前缀。
 *
 * @param pathname 详情页当前 pathname
 * @returns { aid, runId }，无法匹配时返回 null
 */
export function parseRunDetailPath(
  pathname: string,
): { aid: string; runId: string } | null {
  const match = pathname.match(/\/([^/]+)\/sessions\/runs\/([^/?#]+)/);
  if (!match) {
    return null;
  }
  return { aid: match[1], runId: match[2] };
}

/**
 * 由详情页 pathname 派生「返回会话列表页」的绝对路径。
 *
 * @param detailPathname 详情页当前 pathname（…/:aid/sessions/runs/:runId）
 * @returns 会话列表页绝对路径 …/:aid/sessions
 */
export function buildSessionsListPath(detailPathname: string): string {
  // 剥掉尾部的 /runs/:runId；不含该段时原样返回（安全兜底）。
  return detailPathname.replace(/\/runs\/[^/?#]+\/?$/, "");
}
