import { useEffect, useMemo, useState, useDeferredValue } from "react";
import { useParams } from "react-router-dom";
import { Card, Modal, Table, Button, Tabs } from "@agentscope-ai/design";
import { Suspense } from "react";
import { lazyImportWithRetry } from "../../../utils/lazyWithRetry";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import {
  createColumns,
  FilterBar,
  formatTime,
  type Session,
} from "./components";
import { useSessions } from "./useSessions";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import { ChannelIcon } from "../Channels/components";
import styles from "./index.module.less";

// 运行日志视图懒加载：不进首屏 bundle（体积门禁 + 循环依赖检查）。
const LazyRunLogs = lazyImportWithRetry(
  "../../pages/Control/Sessions/RunLogs",
);

function SessionsPage() {
  const { t } = useTranslation();
  // 详情页内时 :aid 显式指定数据域；旧路径/独立挂载时回退 selectedAgent（借壳）
  const { aid } = useParams<{ aid: string }>();
  const {
    sessions,
    loading,
    deleteSession,
    unarchiveSession,
    batchDeleteSessions,
    batchUnarchiveSessions,
    activeTab,
    setActiveTab,
    archivedCount,
  } = useSessions(aid);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  // Filter states
  const [filterUserId, setFilterUserId] = useState<string>("");
  const [filterChannel, setFilterChannel] = useState<string>("");
  const [filterTitle, setFilterTitle] = useState<string>("");
  const [availableChannels, setAvailableChannels] = useState<string[]>([]);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const deferredTitle = useDeferredValue(filterTitle);

  // 筛选结果用 useMemo 派生，禁止 state + useEffect（sessions 引用
  // 每次 render 都会变化时会造成 setFilteredSessions 无限循环）。
  const filteredSessions = useMemo(() => {
    let result: Session[] = sessions;

    if (filterUserId) {
      result = result.filter(
        (session: Session) =>
          session.user_id?.toLowerCase().includes(filterUserId.toLowerCase()),
      );
    }

    if (filterChannel) {
      result = result.filter(
        (session: Session) => session.channel === filterChannel,
      );
    }

    if (deferredTitle) {
      result = result.filter((session: Session) => {
        const name = session.name || "";
        return name.toLowerCase().includes(deferredTitle.toLowerCase());
      });
    }

    return result;
  }, [sessions, filterUserId, filterChannel, deferredTitle]);

  const { message } = useAppMessage();

  useEffect(() => {
    const fetchChannelTypes = async () => {
      try {
        const types = await api.listChannelTypes();
        setAvailableChannels(types);
      } catch (error) {
        console.error("Failed to load channel types:", error);
      }
    };
    fetchChannelTypes();
  }, []);

  // Clear selection when switching tabs
  useEffect(() => {
    setSelectedRowKeys([]);
  }, [activeTab]);

  const handleDelete = (sessionId: string) => {
    Modal.confirm({
      title: t("sessions.confirmDelete"),
      content: t("sessions.deleteConfirm"),
      okText: t("cronJobs.deleteText"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await deleteSession(sessionId);
      },
    });
  };

  const handleUnarchive = async (session: Session) => {
    await unarchiveSession(session.id);
  };

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) {
      message.warning(t("sessions.batchDeleteConfirm", { count: 0 }));
      return;
    }

    Modal.confirm({
      title: t("sessions.confirmDelete"),
      content: t("sessions.batchDeleteConfirm", {
        count: selectedRowKeys.length,
      }),
      okText: t("cronJobs.deleteText"),
      okType: "danger",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        const success = await batchDeleteSessions(selectedRowKeys as string[]);
        if (success) {
          setSelectedRowKeys([]);
        }
      },
    });
  };

  const handleBatchUnarchive = async () => {
    if (selectedRowKeys.length === 0) return;
    const success = await batchUnarchiveSessions(selectedRowKeys as string[]);
    if (success) {
      setSelectedRowKeys([]);
    }
  };

  const columns = createColumns({
    onDelete: handleDelete,
    onArchiveToggle: handleUnarchive,
    isArchivedTab: true,
  });

  const rowSelection = {
    fixed: true,
    columnWidth: 50,
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys);
    },
  };

  return (
    <div className={styles.sessionsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("sessions.title") }]}
        extra={
          activeTab === "archived" ? (
            <div className={styles.headerRight}>
              <FilterBar
                isMobile={isMobile}
                filterUserId={filterUserId}
                filterChannel={filterChannel}
                filterTitle={filterTitle}
                uniqueChannels={availableChannels}
                onUserIdChange={setFilterUserId}
                onChannelChange={setFilterChannel}
                onTitleChange={setFilterTitle}
              />
              {selectedRowKeys.length > 0 && (
                <>
                  <Button onClick={handleBatchUnarchive}>
                    {t("sessions.archive.batchUnaction", "Batch Unarchive")} (
                    {selectedRowKeys.length})
                  </Button>
                  <Button type="primary" danger onClick={handleBatchDelete}>
                    {t("sessions.batchDeleteButton")} ({selectedRowKeys.length})
                  </Button>
                </>
              )}
            </div>
          ) : undefined
        }
      />

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as "runs" | "archived")}
        items={[
          {
            key: "runs",
            label: t("sessions.runLogs.tab", "运行日志"),
          },
          {
            key: "archived",
            label: `${t(
              "sessions.archivedTab",
              "Archived",
            )} (${archivedCount})`,
          },
        ]}
        style={{ padding: "0 16px" }}
      />

      {activeTab !== "archived" ? (
        <Suspense fallback={null}>
          <LazyRunLogs />
        </Suspense>
      ) : isMobile ? (
        <div className={styles.mobileCardList}>
          {filteredSessions.map((session) => (
            <Card
              key={session.id}
              className={styles.mobileSessionCard}
              size="small"
              styles={{ body: { padding: 24 } }}
            >
              <div className={styles.mobileSessionHeader}>
                <span className={styles.mobileSessionName}>
                  {session.name || session.id}
                </span>
                <span className={styles.mobileSessionChannel}>
                  <ChannelIcon channelKey={session.channel} size={24} />
                </span>
              </div>
              <div className={styles.mobileSessionMeta}>
                <span>ID: {session.id}</span>
                {session.user_id && <span>User: {session.user_id}</span>}
                <span>Created: {formatTime(session.created_at)}</span>
              </div>
              <div className={styles.mobileSessionActions}>
                <Button
                  size="small"
                  className={styles.mobileActionBtn}
                  onClick={() => handleUnarchive(session)}
                >
                  {t("sessions.archive.unaction", "Unarchive")}
                </Button>
                <Button
                  size="small"
                  className={styles.mobileActionBtn}
                  danger
                  onClick={() => handleDelete(session.id)}
                >
                  {t("common.delete")}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card className={styles.tableCard} styles={{ body: { padding: 0 } }}>
          <Table
            columns={columns}
            dataSource={filteredSessions}
            loading={loading}
            rowKey="id"
            rowSelection={rowSelection}
            rowClassName={(record) =>
              selectedRowKeys.includes(record.id) ? styles.selectedRow : ""
            }
            scroll={{ x: 1500 }}
            pagination={{
              pageSize: 10,
              showSizeChanger: false,
            }}
          />
        </Card>
      )}
    </div>
  );
}

export default SessionsPage;
