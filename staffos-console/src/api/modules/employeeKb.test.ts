import { describe, it, expect, vi, afterEach } from "vitest";
import { employeeKbApi } from "./employeeKb";

// Same harness as adminApi.test.ts: mock the shared request() helper and
// assert on the (path, options) shaping each API call produces.
vi.mock("../request", () => ({
  request: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../config", () => ({
  getApiUrl: (path: string) => `http://test/api${path}`,
  getApiToken: () => "token",
}));

vi.mock("../authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer token" }),
}));

import { request } from "../request";

const mockRequest = vi.mocked(request);

afterEach(() => vi.clearAllMocks());

describe("employeeKbApi", () => {
  it("lists accessible spaces", async () => {
    await employeeKbApi.listSpaces();
    expect(mockRequest).toHaveBeenCalledWith("/kb");
  });

  it("creates a personal space with name + description", async () => {
    await employeeKbApi.createSpace({ name: "孕产库", description: "用药检索" });
    expect(mockRequest).toHaveBeenCalledWith("/kb", {
      method: "POST",
      body: JSON.stringify({ name: "孕产库", description: "用药检索" }),
    });
  });

  it("encodes the space id in tree/detail/PUT paths", async () => {
    await employeeKbApi.getTree("a/b");
    expect(mockRequest).toHaveBeenCalledWith(`/kb/${encodeURIComponent("a/b")}/tree`);

    await employeeKbApi.getDoc("a/b", "d/1");
    expect(mockRequest).toHaveBeenCalledWith(
      `/kb/${encodeURIComponent("a/b")}/documents/${encodeURIComponent("d/1")}`,
    );

    await employeeKbApi.saveDoc("a/b", "d/1", "# 甲减");
    expect(mockRequest).toHaveBeenCalledWith(
      `/kb/${encodeURIComponent("a/b")}/documents/${encodeURIComponent("d/1")}`,
      { method: "PUT", body: JSON.stringify({ content_md: "# 甲减" }) },
    );
  });

  it("lists chunks under the document path", async () => {
    await employeeKbApi.listChunks("s1", "d1");
    expect(mockRequest).toHaveBeenCalledWith("/kb/s1/documents/d1/chunks");
  });

  it("posts employee search with optional kb_id and default top_k", async () => {
    await employeeKbApi.search({ query: "左甲状腺素", kb_id: "s1" });
    expect(mockRequest).toHaveBeenCalledWith("/kb/search", {
      method: "POST",
      body: JSON.stringify({ query: "左甲状腺素", kb_id: "s1", top_k: 5 }),
    });

    await employeeKbApi.search({ query: "q", top_k: 10 });
    expect(mockRequest).toHaveBeenCalledWith("/kb/search", {
      method: "POST",
      body: JSON.stringify({ query: "q", top_k: 10 }),
    });
  });

  it("binds a space behind the manage gate and unbinds by space id", async () => {
    await employeeKbApi.bindAgent("ag1", "s1", "备注");
    expect(mockRequest).toHaveBeenCalledWith("/agents/ag1/kb-bindings", {
      method: "PUT",
      body: JSON.stringify({ space_id: "s1", remark: "备注" }),
    });

    await employeeKbApi.unbind("ag1", "s/1");
    expect(mockRequest).toHaveBeenCalledWith(
      `/agents/ag1/kb-bindings/${encodeURIComponent("s/1")}`,
      { method: "DELETE" },
    );

    await employeeKbApi.listBindings("ag1");
    expect(mockRequest).toHaveBeenCalledWith("/agents/ag1/kb-bindings");
  });

  it("uploads multipart with the `file` field name via raw fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ doc_id: "d1", path: "a.md" }), {
        status: 201,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      const file = new File(["<h1>甲减</h1>"], "guide.html", {
        type: "text/html",
      });
      const result = await employeeKbApi.uploadDoc("s1", file);
      expect(result.doc_id).toBe("d1");
      const [url, init] = fetchMock.mock.calls[0] as unknown as [
        string,
        RequestInit,
      ];
      expect(url).toBe("http://test/api/kb/s1/documents/upload");
      expect(init.method).toBe("POST");
      expect(init.body).toBeInstanceOf(FormData);
      expect((init.body as FormData).get("file")).toBe(file);
      expect(init.headers).toEqual({ Authorization: "Bearer token" });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
