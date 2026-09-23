/**
 * relativeTime — sidebar-friendly "X分钟前" timestamps.
 *
 * Updated strings on ChatSpecView are ISO/UTC from the backend; anything
 * older than a week falls back to the calendar date so the label never
 * overflows the narrow sidebar column.
 */
export function relativeTime(
  input: string | number | Date | null | undefined,
  now: number = Date.now(),
): string {
  if (input === null || input === undefined || input === "") {
    return "";
  }
  const t =
    input instanceof Date ? input.getTime() : new Date(input).getTime();
  if (!Number.isFinite(t)) {
    return "";
  }
  const diffSeconds = Math.max(0, Math.floor((now - t) / 1000));
  if (diffSeconds < 60) {
    return "刚刚";
  }
  if (diffSeconds < 3600) {
    return `${Math.floor(diffSeconds / 60)}分钟前`;
  }
  if (diffSeconds < 86400) {
    return `${Math.floor(diffSeconds / 3600)}小时前`;
  }
  if (diffSeconds < 86400 * 7) {
    return `${Math.floor(diffSeconds / 86400)}天前`;
  }
  const d = new Date(t);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
