import { describe, expect, it } from "vitest";

import { relativeTime } from "./relativeTime";

// Fixed reference point so thresholds are exact regardless of run time.
const NOW = new Date("2026-08-16T12:00:00Z").getTime();

describe("relativeTime", () => {
  it("空输入返回空串", () => {
    expect(relativeTime(null, NOW)).toBe("");
    expect(relativeTime(undefined, NOW)).toBe("");
    expect(relativeTime("", NOW)).toBe("");
  });

  it("无法解析的输入返回空串", () => {
    expect(relativeTime("not-a-date", NOW)).toBe("");
  });

  it("一分钟内显示「刚刚」", () => {
    expect(relativeTime(new Date(NOW - 30_000), NOW)).toBe("刚刚");
    expect(relativeTime(new Date(NOW - 59_000), NOW)).toBe("刚刚");
  });

  it("一小时内显示「X分钟前」", () => {
    expect(relativeTime(new Date(NOW - 60_000), NOW)).toBe("1分钟前");
    expect(relativeTime(new Date(NOW - 90_000), NOW)).toBe("1分钟前");
    expect(relativeTime(new Date(NOW - 25 * 60_000), NOW)).toBe("25分钟前");
  });

  it("一天内显示「X小时前」", () => {
    expect(relativeTime(new Date(NOW - 3_600_000), NOW)).toBe("1小时前");
    expect(relativeTime(new Date(NOW - 23 * 3_600_000), NOW)).toBe("23小时前");
  });

  it("一周内显示「X天前」", () => {
    expect(relativeTime(new Date(NOW - 24 * 3_600_000), NOW)).toBe("1天前");
    expect(relativeTime(new Date(NOW - 6 * 86_400_000), NOW)).toBe("6天前");
  });

  it("超过一周回落为日历日期", () => {
    expect(relativeTime(new Date("2026-08-08T12:00:00Z"), NOW)).toMatch(
      /^2026-08-0[89]$/,
    );
  });

  it("未来时间戳钳制为「刚刚」而非负数", () => {
    expect(relativeTime(new Date(NOW + 120_000), NOW)).toBe("刚刚");
  });

  it("接受 ISO 字符串输入（后端 ChatSpecView.updated_at 形态）", () => {
    expect(relativeTime("2026-08-16T11:30:00Z", NOW)).toBe("30分钟前");
  });
});
