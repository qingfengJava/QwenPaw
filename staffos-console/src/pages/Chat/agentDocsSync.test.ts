import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AGENT_DOCS_CHANGED_EVENT,
  extractIdentityDocRefs,
  wrapResponseForDocSync,
} from "./agentDocsSync";

const syncDocumentsFromFiles = vi.fn();

vi.mock("../../api/modules/agents", () => ({
  agentsApi: {
    get syncDocumentsFromFiles() {
      return syncDocumentsFromFiles;
    },
  },
}));

function streamResponse(text: string, status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

async function drain(response: Response): Promise<void> {
  await new Response(response.body).text();
  // flush 回调内的异步收尾（sync + 事件广播）走微任务/定时器
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("extractIdentityDocRefs", () => {
  it("hits whitelisted identity docs and dedupes", () => {
    // Set 保序去重：同文件只出现一次
    expect(
      extractIdentityDocRefs("帮我编辑 @ PROFILE.md 和 @ PROFILE.md"),
    ).toEqual(["PROFILE.md"]);
  });

  it("ignores non-whitelisted @ references", () => {
    expect(extractIdentityDocRefs("加载 @ urgent-escalation 技能")).toEqual([]);
  });

  it("ignores editor-line references", () => {
    expect(extractIdentityDocRefs("src/app.py:10-20")).toEqual([]);
  });

  it("matches basename for nested paths", () => {
    expect(
      extractIdentityDocRefs("看看 @ nested/dir/PROFILE.md 的内容"),
    ).toEqual(["PROFILE.md"]);
  });

  it("tolerates CJK punctuation glued to the filename", () => {
    // 中文逗号紧贴文件名：引用解析会把后续文字吞进 path，
    // 白名单判断依赖前缀匹配兜住
    expect(
      extractIdentityDocRefs(
        "帮我编辑 @ SOUL.md，在开始前请先向我确认具体需要修改的内容",
      ),
    ).toEqual(["SOUL.md"]);
  });
});

describe("wrapResponseForDocSync", () => {
  it("passes through untouched when no identity doc referenced", () => {
    const response = streamResponse("data: hi\n\n");
    const wrapped = wrapResponseForDocSync(response, "bot", "随便聊聊");
    expect(wrapped).toBe(response);
  });

  it("passes through non-ok responses", () => {
    const response = streamResponse("err", 500);
    const wrapped = wrapResponseForDocSync(response, "bot", "@ PROFILE.md");
    expect(wrapped).toBe(response);
  });

  it("syncs PG then broadcasts when the turn referenced identity docs", async () => {
    const events: string[] = [];
    const handler = (event: Event) => events.push(event.type);
    window.addEventListener(AGENT_DOCS_CHANGED_EVENT, handler);

    try {
      const response = streamResponse("data: done\n\n");
      const wrapped = wrapResponseForDocSync(
        response,
        "bot",
        "帮我编辑 @ SOUL.md，先确认需求",
      );
      expect(wrapped).not.toBe(response);

      await drain(wrapped);

      expect(syncDocumentsFromFiles).toHaveBeenCalledWith("bot");
      expect(events).toEqual([AGENT_DOCS_CHANGED_EVENT]);
    } finally {
      window.removeEventListener(AGENT_DOCS_CHANGED_EVENT, handler);
    }
  });

  it("still broadcasts when the sync call fails", async () => {
    syncDocumentsFromFiles.mockRejectedValueOnce(new Error("pg down"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const events: string[] = [];
    const handler = (event: Event) => events.push(event.type);
    window.addEventListener(AGENT_DOCS_CHANGED_EVENT, handler);

    try {
      const wrapped = wrapResponseForDocSync(
        streamResponse("data: done\n\n"),
        "bot",
        "@ agent.json",
      );
      await drain(wrapped);

      expect(events).toEqual([AGENT_DOCS_CHANGED_EVENT]);
      expect(warn).toHaveBeenCalled();
    } finally {
      window.removeEventListener(AGENT_DOCS_CHANGED_EVENT, handler);
      warn.mockRestore();
    }
  });
});
