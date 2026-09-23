/**
 * KnowledgeDrawer — per-space management drawer (KB phase 1, T12).
 *
 * Tab "docs": left path tree (pg authoritative plane; on 503 falls back
 * to the flat admin document list with a readable notice) + right MD
 * editor (PUT save, auto version bump) + upload entry + chunk preview
 * table (seq / heading_path). Tab "search": search-test bench querying
 * POST /admin/kb/search-test with score-ranked hits.
 *
 * The parent remounts this drawer per space (key={kb.id}), so switching
 * spaces resets every piece of inner state (联动清空).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tabs,
  Tree,
  Upload,
} from "antd";
import type { DataNode } from "antd/es/tree";
import { DeleteOutlined, SaveOutlined, UploadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { adminKbApi } from "../../api/modules/admin";
import type {
  KbConflictRow,
  KbDocumentView,
  KbReviewAction,
  KbSearchTestHit,
} from "../../api/modules/admin";
import { employeeKbApi } from "../../api/modules/employeeKb";
import type { KbChunk, KbDocDetail, KbTreeNode } from "../../api/modules/employeeKb";
import { useAppMessage } from "../../hooks/useAppMessage";
import type { KnowledgeBase } from "../../api/modules/admin";
import { kbRequestError } from "./kbErrors";
import styles from "./admin.module.less";

interface SelectedDoc {
  docId: string;
  title: string;
}

const STATUS_LABEL_KEY: Record<string, string> = {
  pending: "knowledge.statusPending",
  processing: "knowledge.statusProcessing",
  ready: "knowledge.statusReady",
  failed: "knowledge.statusFailed",
};

const STATUS_TONE_CLASS: Record<string, string> = {
  ready: styles.toneGreen,
  processing: styles.toneBlue,
  pending: styles.toneAmber,
  failed: styles.toneRed,
};

/** 日期格式化（有效期列；空值显示破折号）。 */
function formatDate(value: string | undefined | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD") : "—";
}

/** 知识生命周期状态 → 描述文案映射（T7 治理 tab；单一来源后端枚举）。 */
const KB_STATUS_LABEL_KEY: Record<string, string> = {
  draft: "knowledge.kbStatusDraft",
  in_review: "knowledge.kbStatusInReview",
  published: "knowledge.kbStatusPublished",
  archived: "knowledge.kbStatusArchived",
};

const KB_STATUS_TONE_CLASS: Record<string, string> = {
  published: styles.toneGreen,
  in_review: styles.toneBlue,
  draft: styles.toneAmber,
  archived: styles.toneGray,
};

/** 知识条目状态 Tag（枚举 → 描述文本，禁止前端硬编码文案）。 */
function KbStatusTag({ status }: { status: string }) {
  const { t } = useTranslation();
  const labelKey = KB_STATUS_LABEL_KEY[status];
  return (
    <span
      className={`${styles.toneTag} ${
        KB_STATUS_TONE_CLASS[status] ?? styles.toneGray
      }`}
    >
      {labelKey ? t(labelKey, status) : status}
    </span>
  );
}

/** 各状态下可执行的生命周期动作（draft→提交→审核→发布→归档）。 */
const KB_STATUS_ACTIONS: Record<string, KbReviewAction[]> = {
  draft: ["submit"],
  in_review: ["approve", "reject"],
  published: ["archive"],
  archived: [],
};

/** ingest_status → localized description tag (枚举展示描述文本). */
function StatusTag({ status }: { status: string }) {
  const { t } = useTranslation();
  if (!status) return null;
  const labelKey = STATUS_LABEL_KEY[status];
  return (
    <span
      className={`${styles.toneTag} ${STATUS_TONE_CLASS[status] ?? styles.toneGray}`}
      style={{ marginLeft: 8 }}
    >
      {labelKey ? t(labelKey, status) : status}
    </span>
  );
}

/** Flatten the backend tree into a path → node index for selection. */
function indexTree(
  nodes: KbTreeNode[],
  acc: Map<string, KbTreeNode> = new Map(),
): Map<string, KbTreeNode> {
  for (const node of nodes) {
    acc.set(node.path, node);
    if (node.children.length) indexTree(node.children, acc);
  }
  return acc;
}

function toTreeData(nodes: KbTreeNode[]): DataNode[] {
  return nodes.map((node) => ({
    key: node.path,
    title: (
      <span className={styles.treeNodeTitle}>
        {node.name}
        {node.doc_id ? <StatusTag status={node.ingest_status} /> : null}
      </span>
    ),
    selectable: node.doc_id !== null,
    children: node.children.length ? toTreeData(node.children) : undefined,
  }));
}

interface KnowledgeDrawerProps {
  kb: KnowledgeBase;
  onClose: () => void;
}

function KnowledgeDrawer({ kb, onClose }: KnowledgeDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  // 请求代际守卫：selectDoc / loadChunks / handleSave 共用；切文档或保存
  // 都开启新代际，使在途旧代际回包直接丢弃——杜绝 A→B 连点时 A 的慢
  // 回包把 A 的全文写进 B 的编辑器（写穿）。
  const seqRef = useRef(0);

  // Tree / flat-list state
  const [treeNodes, setTreeNodes] = useState<KbTreeNode[] | null>(null);
  const [treeIndex, setTreeIndex] = useState<Map<string, KbTreeNode>>(new Map());
  const [treeFallback, setTreeFallback] = useState(false);
  const [treeNotice, setTreeNotice] = useState<string | null>(null);
  const [flatDocs, setFlatDocs] = useState<KbDocumentView[] | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);

  // Selection / editor state
  const [selected, setSelected] = useState<SelectedDoc | null>(null);
  const [detail, setDetail] = useState<KbDocDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [saving, setSaving] = useState(false);

  // Chunk preview state
  const [chunks, setChunks] = useState<KbChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState<string | null>(null);

  // Search-test bench state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTopK, setSearchTopK] = useState(5);
  const [searching, setSearching] = useState(false);
  const [searchHits, setSearchHits] = useState<KbSearchTestHit[] | null>(null);

  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestTitle, setIngestTitle] = useState("");
  const [ingestSource, setIngestSource] = useState("");
  const [ingestText, setIngestText] = useState("");
  const [ingesting, setIngesting] = useState(false);

  // ── 治理 tab（T7）：知识条目表 + 域筛选（联动清空状态筛选）+ 生命周期
  // 操作 + 冲突列表抽屉。域 = doc.source（ingest 时的来源域）。
  const [govDocs, setGovDocs] = useState<KbDocumentView[] | null>(null);
  const [govDomain, setGovDomain] = useState<string>("");
  const [govStatus, setGovStatus] = useState<string>("");
  const [reviewing, setReviewing] = useState(false);
  const [conflictsOpen, setConflictsOpen] = useState(false);
  const [conflicts, setConflicts] = useState<KbConflictRow[] | null>(null);
  const [conflictsLoading, setConflictsLoading] = useState(false);

  const loadFlatDocs = useCallback(async () => {
    setTreeLoading(true);
    try {
      setFlatDocs(await adminKbApi.listDocuments(kb.id));
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setTreeLoading(false);
    }
  }, [kb.id, message, t]);

  const loadTree = useCallback(async () => {
    setTreeLoading(true);
    setTreeNotice(null);
    try {
      const res = await employeeKbApi.getTree(kb.id);
      setTreeNodes(res.nodes);
      setTreeIndex(indexTree(res.nodes));
      setTreeFallback(false);
      setFlatDocs(null);
    } catch (err) {
      // pg 权威面 503：显式提示并回退到管理面平铺文档列表（可继续
      // 上传/导入/删文档/chunk 预览；详情编辑仍受 503 约束）
      setTreeNodes(null);
      setTreeIndex(new Map());
      setTreeFallback(true);
      setTreeNotice(kbRequestError(err, t));
      loadFlatDocs();
    } finally {
      setTreeLoading(false);
    }
  }, [kb.id, loadFlatDocs, t]);

  useEffect(() => {
    loadTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadChunks = useCallback(
    async (docId: string, seq?: number) => {
      // 未显式带代际时（保存后刷新等）自开一代；显式传入则与调用方同代
      const mySeq = seq ?? ++seqRef.current;
      setChunksLoading(true);
      setChunksError(null);
      try {
        const rows = await employeeKbApi.listChunks(kb.id, docId);
        if (mySeq !== seqRef.current) return; // stale 回包丢弃
        setChunks(rows);
      } catch (err) {
        if (mySeq !== seqRef.current) return;
        setChunks([]);
        setChunksError(kbRequestError(err, t));
      } finally {
        if (mySeq === seqRef.current) setChunksLoading(false);
      }
    },
    [kb.id, t],
  );

  const selectDoc = useCallback(
    async (docId: string, title: string) => {
      const seq = ++seqRef.current;
      setSelected({ docId, title });
      setDetail(null);
      setDetailError(null);
      setContent("");
      setChunks([]);
      setChunksError(null);
      // chunks 预览在 json 面也可用，独立于详情请求失败（与详情共用代际）
      loadChunks(docId, seq);
      try {
        const got = await employeeKbApi.getDoc(kb.id, docId);
        if (seq !== seqRef.current) return; // stale：已切到别的文档
        setDetail(got);
        setContent(got.content_md);
      } catch (err) {
        if (seq !== seqRef.current) return;
        setDetailError(kbRequestError(err, t));
      }
    },
    [kb.id, loadChunks, t],
  );

  const handleTreeSelect = (keys: Key[]) => {
    const key = keys[0];
    if (typeof key !== "string") return;
    const node = treeIndex.get(key);
    if (node?.doc_id) selectDoc(node.doc_id, node.title || node.name);
  };

  const handleSave = async () => {
    if (!selected) return;
    const seq = ++seqRef.current;
    setSaving(true);
    try {
      const result = await employeeKbApi.saveDoc(kb.id, selected.docId, content);
      if (seq !== seqRef.current) return; // stale：保存期间已切走
      message.success(
        t("knowledge.saveSuccess", "已保存（v{{version}}，{{count}} 块切片）", {
          version: result.version,
          count: result.chunk_count,
        }),
      );
      // 写后读回最新版本；chunks 随重索引刷新
      try {
        const got = await employeeKbApi.getDoc(kb.id, selected.docId);
        if (seq !== seqRef.current) return;
        setDetail(got);
        setContent(got.content_md);
      } catch {
        // 读回失败不回滚成功语义，保留已保存内容
      }
      loadChunks(selected.docId, seq);
    } catch (err) {
      if (seq !== seqRef.current) return;
      message.error(kbRequestError(err, t));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDoc = async (docId: string) => {
    try {
      await adminKbApi.removeDocument(kb.id, docId);
      // 作废在途详情/chunks 回包，防止已删文档内容写回编辑器
      seqRef.current++;
      message.success(t("knowledge.deleteDocSuccess", "文档已删除"));
      setSelected(null);
      setDetail(null);
      setContent("");
      setChunks([]);
      if (treeFallback) loadFlatDocs();
      else loadTree();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const handleUpload = async (file: File) => {
    try {
      const result = await employeeKbApi.uploadDoc(kb.id, file);
      message.success(
        t("knowledge.uploadSuccess", "上传成功，已进入解析流程（{{path}}）", {
          path: result.path,
        }),
      );
      if (treeFallback) loadFlatDocs();
      else loadTree();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
    // 阻断 antd 默认上传行为
    return false;
  };

  const handleIngest = async () => {
    if (!ingestText.trim()) return;
    setIngesting(true);
    try {
      const result = await adminKbApi.ingest(kb.id, {
        text: ingestText,
        title: ingestTitle,
        source: ingestSource,
      });
      message.success(
        t("knowledge.ingestSuccess", "导入完成，切片 {{count}} 块", {
          count: result.chunk_count,
        }),
      );
      setIngestOpen(false);
      setIngestTitle("");
      setIngestSource("");
      setIngestText("");
      if (treeFallback) loadFlatDocs();
      else loadTree();
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setIngesting(false);
    }
  };

  const handleSearchRun = async () => {
    const query = searchQuery.trim();
    if (!query) return;
    setSearching(true);
    try {
      const result = await adminKbApi.searchTest({
        query,
        kb_id: kb.id,
        top_k: searchTopK,
      });
      setSearchHits(result.hits);
    } catch (err) {
      setSearchHits(null);
      message.error(kbRequestError(err, t));
    } finally {
      setSearching(false);
    }
  };

  // ── 治理 tab（T7）─────────────────────────────────────────────

  const loadGovDocs = useCallback(async () => {
    setGovDocs(null);
    try {
      setGovDocs(await adminKbApi.listDocuments(kb.id));
    } catch (err) {
      setGovDocs([]);
      message.error(kbRequestError(err, t));
    }
  }, [kb.id, message, t]);

  // 域筛选变化 → 联动清空下级状态筛选（规范 §2.8）
  const handleGovDomainChange = (value: string) => {
    setGovDomain(value);
    setGovStatus("");
  };

  const handleReview = async (doc: KbDocumentView, action: KbReviewAction) => {
    setReviewing(true);
    try {
      const result = await adminKbApi.review(kb.id, doc.doc_id, action);
      message.success(
        t("knowledge.reviewSuccess", "已{{action}}：{{doc}}", {
          action,
          doc: doc.title || doc.doc_id,
        }),
      );
      void result;
      loadGovDocs();
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setReviewing(false);
    }
  };

  const loadConflicts = useCallback(async () => {
    setConflictsLoading(true);
    try {
      setConflicts(await adminKbApi.listConflicts(kb.id));
    } catch (err) {
      setConflicts([]);
      message.error(kbRequestError(err, t));
    } finally {
      setConflictsLoading(false);
    }
  }, [kb.id, message, t]);

  const openConflicts = () => {
    setConflictsOpen(true);
    loadConflicts();
  };

  const handleResolveConflict = async (conflictId: number) => {
    try {
      await adminKbApi.resolveConflict(kb.id, conflictId);
      message.success(t("knowledge.conflictResolved", "冲突已标记解决"));
      loadConflicts();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const treeData = treeNodes ? toTreeData(treeNodes) : [];

  // 治理 tab：域下拉选项（当前条目的 distinct source）+ 双维筛选后的条目
  const govDomains = useMemo(() => {
    const set = new Set<string>();
    (govDocs ?? []).forEach((doc) => {
      if (doc.source) set.add(doc.source);
    });
    return Array.from(set).sort();
  }, [govDocs]);

  const govRows = useMemo(
    () =>
      (govDocs ?? []).filter(
        (doc) =>
          (!govDomain || doc.source === govDomain) &&
          (!govStatus || (doc.knowledge_status ?? "published") === govStatus),
      ),
    [govDocs, govDomain, govStatus],
  );

  const governanceTab = (
    <div>
      <div className={styles.kbSearchBar}>
        <Select
          allowClear
          value={govDomain || undefined}
          onChange={(v) => handleGovDomainChange((v as string) ?? "")}
          placeholder={t("knowledge.govDomainPlaceholder", "按域筛选")}
          style={{ width: 180 }}
          options={govDomains.map((d) => ({ value: d, label: d }))}
        />
        <Select
          allowClear
          disabled={!govDomain && !govDocs}
          value={govStatus || undefined}
          onChange={(v) => setGovStatus((v as string) ?? "")}
          placeholder={
            govDomain
              ? t("knowledge.govStatusPlaceholder", "按状态筛选")
              : t("knowledge.govStatusNeedsDomain", "请先选域")
          }
          style={{ width: 180 }}
          options={["draft", "in_review", "published", "archived"].map(
            (s) => ({
              value: s,
              label: t(
                KB_STATUS_LABEL_KEY[s] ?? "",
                s,
              ),
            }),
          )}
        />
        <span style={{ flex: 1 }} />
        <Button onClick={openConflicts}>
          {t("knowledge.conflicts", "冲突列表")}
        </Button>
      </div>
      <Table<KbDocumentView>
        rowKey="doc_id"
        size="small"
        loading={govDocs === null}
        dataSource={govRows}
        pagination={{ pageSize: 8, showSizeChanger: false }}
        locale={{
          emptyText: t("knowledge.govEmpty", "暂无知识条目"),
        }}
        columns={[
          {
            title: t("knowledge.docTitle", "标题"),
            dataIndex: "title",
            align: "center" as const,
            ellipsis: true,
            render: (v: string) => v || "—",
          },
          {
            title: t("knowledge.docSource", "域"),
            dataIndex: "source",
            width: 110,
            align: "center" as const,
            render: (v: string) => v || "—",
          },
          {
            title: t("knowledge.kbStatus", "状态"),
            dataIndex: "knowledge_status",
            width: 110,
            align: "center" as const,
            render: (v: string) => <KbStatusTag status={v || "published"} />,
          },
          {
            title: t("knowledge.validity", "有效期"),
            key: "validity",
            width: 190,
            align: "center" as const,
            render: (_: unknown, doc: KbDocumentView) =>
              `${formatDate(doc.valid_from ?? undefined)} ~ ${formatDate(
                doc.valid_to ?? undefined,
              )}`,
          },
          {
            title: t("knowledge.chunkCount", "切片"),
            dataIndex: "chunk_count",
            width: 72,
            align: "center" as const,
          },
          {
            title: t("knowledge.govActions", "生命周期操作"),
            key: "actions",
            width: 240,
            align: "center" as const,
            render: (_: unknown, doc: KbDocumentView) => {
              const status = doc.knowledge_status ?? "published";
              const actions = KB_STATUS_ACTIONS[status] ?? [];
              if (!actions.length) return "—";
              return actions.map((action) => (
                <Popconfirm
                  key={action}
                  title={t("knowledge.reviewConfirm", "确认{{action}}？", {
                    action,
                  })}
                  onConfirm={() => handleReview(doc, action)}
                >
                  <Button size="small" disabled={reviewing} style={{ marginLeft: 4 }}>
                    {t(`knowledge.action_${action}`, action)}
                  </Button>
                </Popconfirm>
              ));
            },
          },
        ]}
      />
      {/* 冲突列表抽屉（嵌套 Drawer）*/}
      <Drawer
        title={t("knowledge.conflicts", "冲突列表")}
        open={conflictsOpen}
        onClose={() => setConflictsOpen(false)}
        width={640}
      >
        <Table<KbConflictRow>
          rowKey="id"
          size="small"
          loading={conflictsLoading}
          dataSource={conflicts ?? []}
          pagination={false}
          locale={{
            emptyText: t("knowledge.conflictsEmpty", "暂无知识冲突"),
          }}
          columns={[
            {
              title: t("knowledge.conflictType", "类型"),
              dataIndex: "conflict_type",
              align: "center" as const,
            },
            {
              title: t("knowledge.conflictPriority", "优先级"),
              dataIndex: "priority",
              width: 80,
              align: "center" as const,
            },
            {
              title: t("knowledge.conflictStatus", "状态"),
              dataIndex: "resolution_status",
              width: 96,
              align: "center" as const,
            },
            {
              title: t("knowledge.createdAt", "创建于"),
              dataIndex: "created_at",
              width: 120,
              align: "center" as const,
              render: (v: string) => formatDate(v),
            },
            {
              title: t("knowledge.conflictAction", "操作"),
              key: "resolve",
              width: 96,
              align: "center" as const,
              render: (_: unknown, row: KbConflictRow) =>
                row.resolution_status === "open" ? (
                  <Popconfirm
                    title={t(
                      "knowledge.conflictResolveConfirm",
                      "确认标记为已解决？",
                    )}
                    onConfirm={() => handleResolveConflict(row.id)}
                  >
                    <Button size="small">
                      {t("knowledge.conflictResolve", "解决")}
                    </Button>
                  </Popconfirm>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </Drawer>
    </div>
  );

  const docsTab = (
    <div className={styles.kbDocSplit}>
      {/* 左：目录树 / 平铺回退列表 */}
      <div className={styles.kbTreePanel}>
        <div className={styles.kbPanelTitle}>{t("knowledge.tree", "目录树")}</div>
        {treeNotice ? (
          <Alert
            type="warning"
            showIcon
            message={t(
              "knowledge.treePgUnavailable",
              "目录树需要 PG 摄入面（当前不可用），已回退为文档列表",
            )}
            description={treeNotice}
            style={{ marginBottom: 8 }}
          />
        ) : null}
        {treeLoading ? (
          <div className={styles.kbHint}>{t("common.loading", "加载中…")}</div>
        ) : treeData.length ? (
          <Tree
            blockNode
            defaultExpandAll
            selectable
            treeData={treeData}
            onSelect={handleTreeSelect}
          />
        ) : flatDocs && flatDocs.length ? (
          <ul className={styles.kbFlatList}>
            {flatDocs.map((doc) => (
              <li
                key={doc.doc_id}
                className={
                  selected?.docId === doc.doc_id ? styles.kbFlatItemActive : undefined
                }
                onClick={() => selectDoc(doc.doc_id, doc.title || doc.doc_id)}
              >
                <span className={styles.treeNodeTitle} title={doc.title}>
                  {doc.title || doc.doc_id}
                </span>
                <span className={styles.kbFlatCount}>{doc.chunk_count}</span>
              </li>
            ))}
          </ul>
        ) : treeFallback && !flatDocs ? (
          <div>
            <Alert
              type="error"
              showIcon
              message={t("knowledge.flatDocsLoadFailed", "文档列表加载失败")}
            />
            <Button
              size="small"
              style={{ marginTop: 8 }}
              onClick={() => loadFlatDocs()}
            >
              {t("knowledge.retry", "重试")}
            </Button>
          </div>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("knowledge.treeEmpty", "该库暂无文档")}
          />
        )}
      </div>

      {/* 右：MD 编辑器 + 切片预览 */}
      <div className={styles.kbEditorPanel}>
        {!selected ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t(
              "knowledge.editorPlaceholder",
              "从左侧选择一个文档开始编辑",
            )}
            style={{ marginTop: 60 }}
          />
        ) : (
          <>
            <div className={styles.kbDocHead}>
              <span className={styles.kbDocTitle} title={selected.title}>
                {selected.title}
              </span>
              <StatusTag status={detail?.ingest_status ?? ""} />
              {detail ? (
                <span className={styles.kbDocVersion}>
                  {t("knowledge.version", "版本")} v{detail.version}
                </span>
              ) : null}
              <span style={{ flex: 1 }} />
              <Popconfirm
                title={t(
                  "knowledge.deleteDocConfirm",
                  "删除该文档？删除后切片同步移除。",
                )}
                onConfirm={() => handleDeleteDoc(selected.docId)}
              >
                <Button size="small" danger icon={<DeleteOutlined />}>
                  {t("knowledge.deleteDoc", "删除文档")}
                </Button>
              </Popconfirm>
              <Button
                size="small"
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                disabled={!detail || saving}
                onClick={handleSave}
              >
                {t("knowledge.save", "保存")}
              </Button>
            </div>
            {detailError ? (
              <Alert
                type="error"
                showIcon
                message={detailError}
                style={{ marginBottom: 8 }}
              />
            ) : null}
            <Input.TextArea
              className={styles.mdEditor}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              disabled={!detail || saving}
              placeholder={t("knowledge.editorContentPlaceholder", "Markdown 全文")}
            />
            <div className={styles.kbChunksBlock}>
              <div className={styles.kbPanelTitle}>
                {t("knowledge.chunks", "切片预览")}
              </div>
              {chunksError ? (
                <Alert type="error" showIcon message={chunksError} />
              ) : (
                <Table<KbChunk>
                  rowKey="chunk_id"
                  size="small"
                  loading={chunksLoading}
                  dataSource={chunks}
                  pagination={false}
                  locale={{ emptyText: t("knowledge.chunksEmpty", "暂无切片") }}
                  scroll={{ y: 220 }}
                  columns={[
                    {
                      title: t("knowledge.chunkSeq", "序号"),
                      dataIndex: "seq",
                      width: 64,
                      align: "center",
                    },
                    {
                      title: t("knowledge.chunkHeading", "章节路径"),
                      dataIndex: "heading_path",
                      width: 200,
                      align: "center",
                      ellipsis: true,
                      render: (v: string) => v || "—",
                    },
                    {
                      title: t("knowledge.chunkText", "内容"),
                      dataIndex: "text",
                      align: "center",
                      ellipsis: true,
                    },
                  ]}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );

  const searchTab = (
    <div className={styles.kbSearchBench}>
      <div className={styles.kbSearchBar}>
        <Input
          allowClear
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onPressEnter={handleSearchRun}
          placeholder={t(
            "knowledge.searchQueryPlaceholder",
            "输入检索 query，回车或点击测试",
          )}
          style={{ flex: 1, maxWidth: 480 }}
        />
        <span className={styles.kbHint}>{t("knowledge.searchTopK", "返回条数")}</span>
        <InputNumber
          min={1}
          max={50}
          value={searchTopK}
          onChange={(v) => setSearchTopK(v ?? 5)}
          style={{ width: 72 }}
        />
        <Button type="primary" loading={searching} onClick={handleSearchRun}>
          {t("knowledge.searchRun", "测试")}
        </Button>
      </div>
      <Table<KbSearchTestHit>
        rowKey="chunk_id"
        size="small"
        loading={searching}
        dataSource={searchHits ?? []}
        pagination={false}
        locale={{
          emptyText: t(
            "knowledge.searchNoHits",
            searchHits === null
              ? "输入 query 后点击「测试」查看命中"
              : "无命中结果",
          ),
        }}
        columns={[
          {
            title: t("knowledge.chunkSeq", "序号"),
            dataIndex: "seq",
            width: 64,
            align: "center",
          },
          {
            title: t("knowledge.searchDoc", "文档"),
            dataIndex: "title",
            width: 160,
            align: "center",
            ellipsis: true,
            render: (v: string) => v || "—",
          },
          {
            title: t("knowledge.chunkHeading", "章节路径"),
            dataIndex: "heading_path",
            width: 180,
            align: "center",
            ellipsis: true,
            render: (v: string) => v || "—",
          },
          {
            title: t("knowledge.chunkText", "内容"),
            dataIndex: "text",
            align: "center",
            ellipsis: true,
          },
          {
            title: t("knowledge.searchScore", "得分"),
            dataIndex: "score",
            width: 96,
            align: "center",
            render: (v: number) => (typeof v === "number" ? v.toFixed(4) : "—"),
          },
        ]}
      />
    </div>
  );

  return (
    <Drawer
      title={kb.name}
      open
      onClose={onClose}
      width={1020}
      extra={
        <>
          <Upload
            accept=".md,.markdown,.txt,.html,.htm,.pdf,.docx"
            showUploadList={false}
            beforeUpload={(file) => handleUpload(file)}
          >
            <Button icon={<UploadOutlined />}>
              {t("knowledge.upload", "上传文档")}
            </Button>
          </Upload>
          <Button
            type="primary"
            ghost
            onClick={() => setIngestOpen(true)}
            style={{ marginLeft: 8 }}
          >
            {t("knowledge.ingestText", "导入文本")}
          </Button>
        </>
      }
    >
      <Tabs
        defaultActiveKey="docs"
        items={[
          { key: "docs", label: t("knowledge.docsTab", "文档"), children: docsTab },
          {
            key: "governance",
            label: t("knowledge.governanceTab", "治理"),
            children: governanceTab,
          },
          {
            key: "search",
            label: t("knowledge.searchTestTab", "检索测试台"),
            children: searchTab,
          },
        ]}
      />

      <Modal
        title={t("knowledge.ingestText", "导入文本")}
        open={ingestOpen}
        onOk={handleIngest}
        confirmLoading={ingesting}
        onCancel={() => setIngestOpen(false)}
        destroyOnHidden
      >
        <div className={styles.kbIngestForm}>
          <label className={styles.kbIngestLabel}>{t("knowledge.docTitle", "标题")}</label>
          <Input value={ingestTitle} onChange={(e) => setIngestTitle(e.target.value)} />
          <label className={styles.kbIngestLabel}>{t("knowledge.docSource", "来源")}</label>
          <Input
            value={ingestSource}
            onChange={(e) => setIngestSource(e.target.value)}
            placeholder={t("knowledge.ingestSourcePlaceholder", "runbook / wiki / ...")}
          />
          <label className={styles.kbIngestLabel}>{t("knowledge.docText", "正文")}</label>
          <Input.TextArea
            rows={8}
            value={ingestText}
            onChange={(e) => setIngestText(e.target.value)}
          />
        </div>
      </Modal>
    </Drawer>
  );
}

export default KnowledgeDrawer;
