/**
 * WorkbenchVersionsTab — 发布历史（published_experts 不可变快照链）
 * + 档案文档历史（agent_document_revisions，回滚直接生效）。
 *
 * - 发布历史：版本号 / 发布人 / 发布时间（新版本在前）；回滚写回草稿，
 *   需再次「发布」才影响线上；快照只增不可变；
 * - 档案历史：基础档案文件（PROFILE/AGENTS/SOUL/agent.json）的每次
 *   发布/回滚快照；回滚直接生效（production 行 + 文件物化 + 热重载）。
 *
 * 诚实数据原则：从未发布过/无快照时给出明确空态，不造假。
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Empty, Popconfirm, Table, Tag } from "antd";
import { History, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StatusPill } from "@/components/staffdeck";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  adminExpertsApi,
  type ExpertDocRevisionInfo,
  type ExpertPreviewStatus,
  type ExpertVersionInfo,
} from "../../../api/modules/admin";

interface WorkbenchVersionsTabProps {
  expertId: string;
  /** 顶部徽标同源的预览状态（草稿是否有未发布变更）。 */
  preview: ExpertPreviewStatus | null;
  /** 回滚成功后通知布局刷新徽标 / agent 列表。 */
  onChanged: () => void;
}

export default function WorkbenchVersionsTab({
  expertId,
  preview,
  onChanged,
}: WorkbenchVersionsTabProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [versions, setVersions] = useState<ExpertVersionInfo[] | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);

  // ── 档案文档历史（agent_document_revisions）──
  const DOC_FILES = [
    "PROFILE.md",
    "AGENTS.md",
    "SOUL.md",
    "agent.json",
  ] as const;
  const docTypeOf = (name: string) =>
    name === "PROFILE.md"
      ? "profile"
      : name === "AGENTS.md"
        ? "agents"
        : name === "SOUL.md"
          ? "soul"
          : "agent_json";
  const [activeDoc, setActiveDoc] = useState<string>("PROFILE.md");
  const [docRevisions, setDocRevisions] = useState<
    ExpertDocRevisionInfo[] | null
  >(null);
  const [docAvailable, setDocAvailable] = useState(true);
  const [docRollingBack, setDocRollingBack] = useState<number | null>(null);

  const loadDocRevisions = useCallback(async () => {
    try {
      const res = await adminExpertsApi.listDocRevisions(
        expertId,
        docTypeOf(activeDoc),
      );
      setDocRevisions(res.revisions ?? []);
      setDocAvailable(res.available !== false);
    } catch {
      // 未发布过的专家 / 无 PG：诚实空态
      setDocRevisions([]);
      setDocAvailable(false);
    }
  }, [expertId, activeDoc]);

  const load = useCallback(async () => {
    try {
      const res = await adminExpertsApi.listVersions(expertId);
      setVersions(res.versions ?? []);
    } catch (err) {
      message.error(String(err));
      setVersions([]);
    }
  }, [expertId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadDocRevisions();
  }, [loadDocRevisions]);

  const handleRestore = async (version: number) => {
    setRestoring(version);
    try {
      await adminExpertsApi.restoreVersion(expertId, version);
      message.success(
        t(
          "workbench.restoreSuccess",
          "已回滚到 v{{version}}（写入草稿），请检查后点「发布」生效",
          { version },
        ),
      );
      onChanged();
    } catch (err) {
      message.error(String(err));
    } finally {
      setRestoring(null);
    }
  };

  const handleDocRollback = async (version: number) => {
    setDocRollingBack(version);
    try {
      const res = await adminExpertsApi.rollbackDoc(
        expertId,
        docTypeOf(activeDoc),
        version,
      );
      message.success(
        t(
          "workbench.docRollbackSuccess",
          "已回滚 {{file}} 到 v{{version}}，线上已生效",
          { file: activeDoc, version },
        ),
      );
      void loadDocRevisions();
      onChanged();
      return res;
    } catch (err) {
      message.error(String(err));
      return null;
    } finally {
      setDocRollingBack(null);
    }
  };

  if (versions === null) {
    return <Empty description={t("staffdeck.detail.loading", "加载中…")} />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 状态摘要：当前线上版本 + 草稿是否落后 */}
      {preview ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, color: "var(--sd-text-3)" }}>
            {preview.published_version === null
              ? t("workbench.neverPublished", "该员工尚未发布过")
              : t("workbench.liveVersion", "线上版本 v{{v}}", {
                  v: preview.published_version,
                })}
          </span>
          {preview.has_unpublished_changes ? (
            <StatusPill tone="amber">
              {t("workbench.hasDraftChanges", "草稿有未发布变更")}
            </StatusPill>
          ) : (
            <StatusPill tone="green">
              {t("workbench.noDraftChanges", "草稿与线上一致")}
            </StatusPill>
          )}
        </div>
      ) : null}

      <Table<ExpertVersionInfo>
        size="middle"
        rowKey="version"
        dataSource={versions}
        locale={{
          emptyText: t(
            "workbench.versionsEmpty",
            "暂无发布记录（发布后每次生成不可变快照）",
          ),
        }}
        pagination={{ hideOnSinglePage: true, pageSize: 20 }}
        columns={[
          {
            title: t("workbench.colVersion", "版本"),
            dataIndex: "version",
            key: "version",
            width: 120,
            align: "center",
            render: (v: number) => <Tag>v{v}</Tag>,
          },
          {
            title: t("workbench.colPublisher", "发布人"),
            dataIndex: "published_by",
            key: "published_by",
            width: 180,
            align: "center",
          },
          {
            title: t("workbench.colTime", "发布时间"),
            dataIndex: "published_at",
            key: "published_at",
            align: "center",
            render: (value: string | null) => value ?? "—",
          },
          {
            title: t("workbench.colActions", "操作"),
            key: "actions",
            width: 140,
            align: "center",
            render: (_: unknown, record: ExpertVersionInfo) => (
              <Popconfirm
                title={t("workbench.restoreConfirm", "回滚到 v{{version}}？", {
                  version: record.version,
                })}
                description={t(
                  "workbench.restoreHint",
                  "仅写回草稿，点「发布」后才会影响线上",
                )}
                onConfirm={() => handleRestore(record.version)}
              >
                <Button
                  size="small"
                  icon={<RotateCcw size={13} />}
                  loading={restoring === record.version}
                >
                  {t("workbench.restore", "回滚")}
                </Button>
              </Popconfirm>
            ),
          },
        ]}
      />

      {/* ── 档案文档历史（回滚直接生效）── */}
      <div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 8,
          }}
        >
          <History size={15} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            {t("workbench.docHistoryTitle", "档案历史")}
          </span>
          <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
            {t(
              "workbench.docHistoryHint",
              "基础档案的每次发布/回滚快照；回滚直接生效，无需再次发布",
            )}
          </span>
        </div>
        <div
          style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}
        >
          {DOC_FILES.map((name) => (
            <Button
              key={name}
              size="small"
              type={name === activeDoc ? "primary" : "default"}
              onClick={() => setActiveDoc(name)}
            >
              {name}
            </Button>
          ))}
        </div>
        {docRevisions === null ? (
          <Empty description={t("staffdeck.detail.loading", "加载中…")} />
        ) : !docAvailable ? (
          <Empty
            description={t(
              "workbench.docHistoryUnavailable",
              "档案版本链需启用 PostgreSQL 档案存储",
            )}
          />
        ) : (
          <Table<ExpertDocRevisionInfo>
            size="small"
            rowKey="version"
            dataSource={docRevisions}
            locale={{
              emptyText: t(
                "workbench.docHistoryEmpty",
                "暂无该档案的版本快照（发布后自动生成）",
              ),
            }}
            pagination={{ hideOnSinglePage: true, pageSize: 10 }}
            columns={[
              {
                title: t("workbench.colVersion", "版本"),
                dataIndex: "version",
                key: "version",
                width: 100,
                align: "center",
                render: (v: number) => <Tag>v{v}</Tag>,
              },
              {
                title: t("workbench.colPublisher", "操作人"),
                dataIndex: "published_by",
                key: "published_by",
                width: 180,
                align: "center",
                render: (v: string | null) => v ?? "—",
              },
              {
                title: t("workbench.colTime", "快照时间"),
                dataIndex: "published_at",
                key: "published_at",
                align: "center",
                render: (value: string | null) => value ?? "—",
              },
              {
                title: t("workbench.colActions", "操作"),
                key: "actions",
                width: 140,
                align: "center",
                render: (_: unknown, record: ExpertDocRevisionInfo) => (
                  <Popconfirm
                    title={t(
                      "workbench.docRollbackConfirm",
                      "回滚 {{file}} 到 v{{version}}？",
                      { file: activeDoc, version: record.version },
                    )}
                    description={t(
                      "workbench.docRollbackHint",
                      "直接生效线上：production 行 + 工作区文件同步更新",
                    )}
                    onConfirm={() => handleDocRollback(record.version)}
                  >
                    <Button
                      size="small"
                      icon={<RotateCcw size={13} />}
                      loading={docRollingBack === record.version}
                    >
                      {t("workbench.restore", "回滚")}
                    </Button>
                  </Popconfirm>
                ),
              },
            ]}
          />
        )}
      </div>
    </div>
  );
}
