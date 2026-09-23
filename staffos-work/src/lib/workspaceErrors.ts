/**
 * Shared workspace-error translation: backend rejections (FastAPI detail
 * strings) mapped to readable Chinese for every bind/unbind surface —
 * the composer WorkspaceSelector and the 保存到工作空间 picker modal
 * must show the SAME wording for the same business error.
 */

/** Map backend workspace rejections to readable Chinese messages. */
export function friendlyWorkspaceError(err: unknown, fallback: string): string {
  const message = err instanceof Error ? err.message : String(err);
  if (/in progress|409/i.test(message)) {
    return "回复中的任务暂不能切换工作空间，请等本轮回复结束后再试";
  }
  if (/already registered|已注册/i.test(message)) {
    return "该目录已注册为工作空间";
  }
  if (/unavailable|503/i.test(message)) {
    return "当前部署不支持系统目录选择，请手动填写路径";
  }
  return `${fallback}：${message}`;
}
