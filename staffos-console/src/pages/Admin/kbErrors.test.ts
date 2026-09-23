/**
 * kbErrors.test.ts — kbRequestError mapping contract (T12 review fix).
 *
 * Status-first mapping (structured `err.status` attached by request())
 * with message-text scanning as the fallback for legacy/native errors.
 */
import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { kbRequestError } from "./kbErrors";

const PG_MSG = "PG 摄入面暂不可用，请稍后重试或联系管理员";
const FORBIDDEN_MSG = "没有该知识库的操作权限";
const NOT_FOUND_MSG = "资源不存在或已被删除";

/** Minimal t() standing in for i18next: returns the fallback text. */
const t = ((key: string, fallback?: string) => fallback ?? key) as unknown as TFunction;

describe("kbRequestError", () => {
  it("maps structured status=503 to the pg-unavailable guidance", () => {
    const err = Object.assign(new Error("no digits in here"), { status: 503 });
    expect(kbRequestError(err, t)).toBe(PG_MSG);
  });

  it("maps structured status=403 to the forbidden guidance", () => {
    const err = Object.assign(new Error("owner gate"), { status: 403 });
    expect(kbRequestError(err, t)).toBe(FORBIDDEN_MSG);
  });

  it("maps structured status=404 to the not-found guidance", () => {
    const err = Object.assign(new Error("gone"), { status: 404 });
    expect(kbRequestError(err, t)).toBe(NOT_FOUND_MSG);
  });

  it("falls back to message scanning when no structured status exists", () => {
    expect(kbRequestError(new Error("Request failed: 503 Gateway"), t)).toBe(PG_MSG);
    expect(kbRequestError(new Error("Upload failed: 403 - denied"), t)).toBe(
      FORBIDDEN_MSG,
    );
    expect(kbRequestError(new Error("... 404 ..."), t)).toBe(NOT_FOUND_MSG);
  });

  it("prefers the structured status over misleading message text", () => {
    const err = Object.assign(new Error("mentions 404 but is not"), {
      status: 403,
    });
    expect(kbRequestError(err, t)).toBe(FORBIDDEN_MSG);
  });

  it("returns the raw message when nothing matches", () => {
    expect(kbRequestError(new Error("boom"), t)).toBe("boom");
    expect(kbRequestError("plain string", t)).toBe("plain string");
  });
});
