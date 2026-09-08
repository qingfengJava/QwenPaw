/**
 * Shared formatting helpers for the run-log list and detail page.
 * Extracted from the former detail drawer so both surfaces (and the
 * detail page) import from one dependency-free module.
 */

/** 12500 → "12.50 s"; 950 → "950 ms"; 95000 → "1.58 min". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${(ms / 60000).toFixed(2)} min`;
}

/** 2026-09-02 15:42:01 style local clock from epoch seconds. */
export function formatClock(epochSeconds: number | undefined | null): string {
  if (!epochSeconds) {
    return "—";
  }
  const date = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
}

/** Best-effort text rendering of a node detail payload. */
export function serializeDetail(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Clipboard write that stays silent in insecure contexts. */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Clipboard unavailable (e.g. insecure context); ignore silently.
  }
}
