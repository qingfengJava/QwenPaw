/**
 * WorkbenchVersionsTab — 发布历史（published_experts 不可变快照链）。
 *
 * - 列表：版本号 / 发布人 / 发布时间（新版本在前，服务端已排序）；
 * - 回滚：快照 spec 写回草稿（剥离运行时字段），线上不受影响，
 *   需在工作台再次点「发布」才生效；快照只增不可变。
 *
 * 诚实数据原则：从未发布过（快照为空）时给出明确空态，不造假。
 */
import { useCallback, useEffect, useState } from "react";
import { Button, Empty, Popconfirm, Table, Tag } from "antd";
import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StatusPill } from "@/components/staffdeck";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  adminExpertsApi,
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
    </div>
  );
}
