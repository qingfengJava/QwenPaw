/**
 * KnowledgeDrawer.test.tsx — stale-response race guard (T12 review fix).
 *
 * Pins the seqRef generation guard: clicking doc A then doc B must make
 * A's slow detail response a no-op, so the editor can never end up
 * showing (and then PUTting) A's content while selected.docId === B
 * (cross-document write-through). Also covers the retryable fallback
 * state when both the pg tree (503) and the admin flat list fail.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getTree: vi.fn(),
  getDoc: vi.fn(),
  listChunks: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("../../api/modules/employeeKb", () => ({
  employeeKbApi: {
    getTree: mocks.getTree,
    getDoc: mocks.getDoc,
    listChunks: mocks.listChunks,
  },
}));

vi.mock("../../api/modules/admin", () => ({
  adminKbApi: {
    listDocuments: mocks.listDocuments,
    removeDocument: vi.fn(),
    ingest: vi.fn(),
    searchTest: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
  }),
}));

import KnowledgeDrawer from "./KnowledgeDrawer";
import type { KnowledgeBase } from "../../api/modules/admin";

const kb = { id: "kb-1", name: "KB One" } as unknown as KnowledgeBase;

const TREE_NODES = [
  {
    name: "a.md",
    path: "a.md",
    doc_id: "doc-a",
    title: "Doc A",
    ingest_status: "ready",
    children: [],
  },
  {
    name: "b.md",
    path: "b.md",
    doc_id: "doc-b",
    title: "Doc B",
    ingest_status: "ready",
    children: [],
  },
];

function docDetail(docId: string, content: string) {
  return {
    doc_id: docId,
    kb_id: "kb-1",
    title: docId === "doc-a" ? "Doc A" : "Doc B",
    path: docId === "doc-a" ? "a.md" : "b.md",
    source: "",
    ingest_status: "ready",
    version: 1,
    content_md: content,
    updated_by: "",
    created_at: "",
    updated_at: "",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("KnowledgeDrawer stale-response guard", () => {
  it("drops doc A's slow detail response after doc B is selected", async () => {
    mocks.getTree.mockResolvedValue({ kb_id: "kb-1", nodes: TREE_NODES });
    let resolveA!: (v: unknown) => void;
    const slowA = new Promise((resolve) => {
      resolveA = resolve;
    });
    mocks.getDoc
      .mockImplementationOnce(() => slowA)
      .mockResolvedValue(docDetail("doc-b", "B-CONTENT"));
    mocks.listChunks.mockResolvedValue([]);

    render(<KnowledgeDrawer kb={kb} onClose={vi.fn()} />);

    // Wait for the tree to render before interacting. Tree rows show the
    // file name (node.name), so click targets are "a.md" / "b.md".
    await waitFor(() =>
      expect(document.body.innerHTML.includes("ant-tree")).toBe(true),
    );

    // Select A (its detail response stays pending), then B immediately.
    fireEvent.click(await screen.findByText("a.md"));
    await waitFor(() => expect(mocks.getDoc).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("b.md"));
    await waitFor(() => expect(mocks.getDoc).toHaveBeenCalledTimes(2));

    // B resolves and owns the editor.
    const editor = (await screen.findByPlaceholderText(
      "Markdown 全文",
    )) as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe("B-CONTENT"));

    // A's slow response lands on a stale generation: must be dropped.
    await act(async () => {
      resolveA(docDetail("doc-a", "A-CONTENT"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(editor.value).toBe("B-CONTENT");
    expect(editor.value).not.toContain("A-CONTENT");
    expect(screen.getByText("Doc B")).toBeInTheDocument();
  });

  it("shows a retryable error state when tree 503 fallback list fails too", async () => {
    mocks.getTree.mockRejectedValue(
      Object.assign(new Error("pg plane unavailable"), { status: 503 }),
    );
    mocks.listDocuments.mockRejectedValue(new Error("network down"));

    render(<KnowledgeDrawer kb={kb} onClose={vi.fn()} />);

    // P2-2: fallback failure must NOT render the misleading empty state.
    expect(await screen.findByText("文档列表加载失败")).toBeInTheDocument();
    expect(screen.queryByText("该库暂无文档")).not.toBeInTheDocument();
    // antd Button auto-inserts a space between two CJK glyphs ("重 试").
    const retryBtn = await screen.findByRole("button", {
      name: /重\s*试/,
    });
    // Retry recovers into the flat document list.
    mocks.listDocuments.mockResolvedValue([
      { doc_id: "d1", title: "Flat Doc", chunk_count: 3 },
    ]);
    fireEvent.click(retryBtn);
    await waitFor(() => expect(mocks.listDocuments).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Flat Doc")).toBeInTheDocument();
  });
});
