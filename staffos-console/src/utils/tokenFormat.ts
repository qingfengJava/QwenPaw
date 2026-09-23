/**
 * Token 数量紧凑格式化（跨模块共享）。
 *
 * 131072 -> "128K"、1048576 -> "1M"、512 -> "512"。
 * 供模型选择器上下文徽标与模型配置编辑器档位使用，
 * 保证两处展示口径一致。
 *
 * @author qingfeng
 */
export function formatTokenCount(tokens: number): string {
  if (tokens >= 1024 * 1024 && tokens % (1024 * 1024) === 0) {
    return `${tokens / (1024 * 1024)}M`;
  }

  if (tokens >= 1024) {
    return `${Math.round(tokens / 1024)}K`;
  }

  return String(tokens);
}
