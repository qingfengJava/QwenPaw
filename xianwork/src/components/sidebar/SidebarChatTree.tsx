/**
 * SidebarChatTree — the「任务 / 空间」sidebar tree and its whole
 * interaction state machine, consuming the shared chats store.
 *
 * Owns: section/workspace collapse, inline renames (chats + folders),
 * batch mode (select-all / delete / archive, running chats excluded),
 * the six-entry chat context menu + workspace context menu, and every
 * modal (新建空间 / 保存到工作空间 / 打开文件夹降级 / 删除确认).
 *
 * The parent (MainLayout) only renders this inside the nav list — it
 * stays a pure layout shell.
 */
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { workspaceApi } from "../../api/modules";
import type { ChatSpecView, WorkspaceView } from "../../api/modules";
import { useAllChats, useChatsStore } from "../../stores/chats";
import { useSidebarGroups } from "./useSidebarGroups";
import { useToast } from "../Toast";
import { exportChatMarkdown } from "../../lib/shareTask";
import Modal from "../Modal";
import SidebarSection from "./SidebarSection";
import ChatListItem from "./ChatListItem";
import WorkspaceGroup from "./WorkspaceGroup";
import BatchBar from "./BatchBar";
import SessionContextMenu, { ContextMenu } from "./SessionContextMenu";
import type { ContextMenuEntry } from "./SessionContextMenu";
import OpenFolderModal from "./OpenFolderModal";
import WorkspaceDialog from "../workspace/WorkspaceDialog";
import WorkspacePickerModal from "../workspace/WorkspacePickerModal";

interface Anchor {
  x: number;
  y: number;
}

function anchorOf(e: React.MouseEvent): Anchor {
  return { x: e.clientX, y: e.clientY };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function SidebarChatTree() {
  const toast = useToast();
  const location = useLocation();
  const activeChatId =
    new URLSearchParams(location.search).get("chat") ?? "";

  const { unboundChats, workspaces } = useSidebarGroups();
  const allChats = useAllChats();
  const selectableIds = useMemo(
    () => allChats.filter((c) => c.status !== "running").map((c) => c.id),
    [allChats],
  );

  // Collapse state ---------------------------------------------------------
  const [tasksCollapsed, setTasksCollapsed] = useState(false);
  const [spacesCollapsed, setSpacesCollapsed] = useState(false);
  const [collapsedWorkspaces, setCollapsedWorkspaces] = useState<Set<string>>(
    () => new Set(),
  );

  // Inline rename state (chats + folder rows) ------------------------------
  const [renamingChatId, setRenamingChatId] = useState<string | null>(null);
  const [renamingWorkspaceId, setRenamingWorkspaceId] = useState<
    string | null
  >(null);

  // Batch mode --------------------------------------------------------------
  const [batchMode, setBatchMode] = useState(false);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchConfirmDelete, setBatchConfirmDelete] = useState(false);

  // Context menus -----------------------------------------------------------
  const [chatMenu, setChatMenu] = useState<{
    anchor: Anchor;
    chat: ChatSpecView;
  } | null>(null);
  const [wsMenu, setWsMenu] = useState<{
    anchor: Anchor;
    ws: WorkspaceView;
  } | null>(null);

  // Modals ------------------------------------------------------------------
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [pickerChatIds, setPickerChatIds] = useState<string[] | null>(null);
  const [deleteChat, setDeleteChat] = useState<ChatSpecView | null>(null);
  const [deleteWorkspace, setDeleteWorkspace] = useState<WorkspaceView | null>(
    null,
  );
  const [folderModal, setFolderModal] = useState<{
    path: string;
    hint?: string;
  } | null>(null);

  // Initial load (single source of truth — no per-surface refetching).
  useEffect(() => {
    void useChatsStore.getState().reload();
  }, []);

  const findBoundWorkspace = (chatId: string): WorkspaceView | null =>
    workspaces.find((w) => (w.chats ?? []).some((c) => c.id === chatId)) ??
    null;

  const exitBatch = () => {
    setBatchMode(false);
    setCheckedIds(new Set());
    setBatchConfirmDelete(false);
  };

  // --- chat actions ---------------------------------------------------------

  const handleRenamed = async (chatId: string, name: string) => {
    try {
      await useChatsStore.getState().renameChat(chatId, name);
      toast.success("已重命名");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const handleRemoveChat = async () => {
    if (!deleteChat) return;
    const chatId = deleteChat.id;
    setDeleteChat(null);
    try {
      await useChatsStore.getState().removeChat(chatId);
      if (checkedIds.has(chatId)) {
        setCheckedIds((prev) => {
          const next = new Set(prev);
          next.delete(chatId);
          return next;
        });
      }
      toast.success("任务已删除");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const handleShare = async (chat: ChatSpecView) => {
    try {
      const name = await exportChatMarkdown(chat);
      toast.success(`已导出「${name}.md」`);
    } catch {
      toast.error("导出失败");
    }
  };

  const handleTogglePin = async (chat: ChatSpecView) => {
    const next = !chat.pinned;
    try {
      await useChatsStore.getState().togglePin(chat.id, next);
      toast.success(next ? "已置顶" : "已取消置顶");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const handleArchiveChat = async (chat: ChatSpecView) => {
    try {
      const result = await useChatsStore.getState().archiveChat(chat.id);
      if (result.succeeded.length > 0) {
        toast.success(`已归档「${chat.name || "新任务"}」`);
      } else {
        const reason = result.failed[0]?.reason;
        toast.error(
          reason === "in_progress" ? "回复中的任务不可归档" : "归档失败",
        );
      }
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const openFolderOfChat = (chat: ChatSpecView) => {
    const ws = findBoundWorkspace(chat.id);
    if (!ws) {
      setFolderModal({ path: "" });
      return;
    }
    workspaceApi
      .openFolder(ws.id)
      .then((r) => toast.success(`已打开 ${r.path}`))
      .catch(() => setFolderModal({ path: ws.dir_path }));
  };

  const openFolderOfWs = (ws: WorkspaceView) => {
    workspaceApi
      .openFolder(ws.id)
      .then((r) => toast.success(`已打开 ${r.path}`))
      .catch(() => setFolderModal({ path: ws.dir_path }));
  };

  // --- batch actions --------------------------------------------------------

  const toggleCheck = (chatId: string, checked: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(chatId);
      } else {
        next.delete(chatId);
      }
      return next;
    });
  };

  const toggleAll = (checked: boolean) => {
    setCheckedIds(checked ? new Set(selectableIds) : new Set());
  };

  const runBatchDelete = async () => {
    const ids = [...checkedIds];
    setBatchConfirmDelete(false);
    setBatchBusy(true);
    try {
      await useChatsStore.getState().batchRemove(ids);
      toast.success(`已删除 ${ids.length} 个任务`);
      exitBatch();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBatchBusy(false);
    }
  };

  const runBatchArchive = async () => {
    const ids = [...checkedIds];
    setBatchBusy(true);
    try {
      const result = await useChatsStore.getState().batchArchive(ids);
      const failedPart =
        result.failed.length > 0 ? `，${result.failed.length} 个失败` : "";
      toast.success(`已归档 ${result.succeeded.length} 个任务${failedPart}`);
      setCheckedIds(new Set(result.failed.map((f) => f.chat_id)));
      if (result.failed.length === 0) {
        exitBatch();
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBatchBusy(false);
    }
  };

  // --- workspace actions ------------------------------------------------------

  const handleWsRenamed = async (workspaceId: string, name: string) => {
    try {
      await workspaceApi.update(workspaceId, name);
      await useChatsStore.getState().reload();
      toast.success("空间已重命名");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const handleRemoveWorkspace = async () => {
    if (!deleteWorkspace) return;
    const ws = deleteWorkspace;
    setDeleteWorkspace(null);
    try {
      const r = await workspaceApi.remove(ws.id);
      await useChatsStore.getState().reload();
      toast.success(
        `空间「${ws.name}」已删除，${r.unbound_chats} 个任务已回到任务区（磁盘文件未动）`,
      );
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const wsMenuEntries = (ws: WorkspaceView): ContextMenuEntry[] => [
    {
      key: "open-folder",
      label: "打开文件夹",
      icon: "fa-regular fa-folder-open",
      onClick: () => openFolderOfWs(ws),
    },
    {
      key: "rename",
      label: "重命名空间",
      icon: "fa-regular fa-pen-to-square",
      onClick: () => setRenamingWorkspaceId(ws.id),
    },
    {
      key: "delete",
      label: "删除空间",
      icon: "fa-regular fa-trash-can",
      danger: true,
      onClick: () => setDeleteWorkspace(ws),
    },
  ];

  const menuChat = chatMenu?.chat;

  return (
    <>
      <div className="sidebar-tree">
        {batchMode && (
          <BatchBar
            selectedCount={checkedIds.size}
            selectableCount={selectableIds.length}
            allSelected={
              selectableIds.length > 0 &&
              selectableIds.every((id) => checkedIds.has(id))
            }
            busy={batchBusy}
            onToggleAll={toggleAll}
            onDelete={() => setBatchConfirmDelete(true)}
            onArchive={() => void runBatchArchive()}
            onExit={exitBatch}
          />
        )}

        <SidebarSection
          title="任务"
          count={unboundChats.length}
          collapsed={tasksCollapsed}
          onToggle={() => setTasksCollapsed((v) => !v)}
          extra={
            !batchMode && allChats.length > 0 ? (
              <button
                type="button"
                className="sidebar-icon-btn"
                onClick={() => {
                  setBatchMode(true);
                  setCheckedIds(new Set());
                }}
                title="批量选择任务"
                aria-label="批量选择任务"
              >
                <i className="fa-regular fa-square-check" />
              </button>
            ) : undefined
          }
        >
          <ul className="sidebar-chat-list">
            {unboundChats.map((chat) => (
              <ChatListItem
                key={chat.id}
                chat={chat}
                active={chat.id === activeChatId}
                batchMode={batchMode}
                checked={checkedIds.has(chat.id)}
                renaming={renamingChatId === chat.id}
                onRenamingChange={(chatId, renaming) =>
                  setRenamingChatId(renaming ? chatId : null)
                }
                onToggleCheck={toggleCheck}
                onOpenMenu={(chat, anchor) => setChatMenu({ anchor, chat })}
                onArchive={(chat) => void handleArchiveChat(chat)}
                onTogglePin={(chat) => void handleTogglePin(chat)}
                onRenamed={(chatId, name) => void handleRenamed(chatId, name)}
              />
            ))}
            {unboundChats.length === 0 && (
              <li className="workspace-empty">暂无任务</li>
            )}
          </ul>
        </SidebarSection>

        <SidebarSection
          title="空间"
          count={workspaces.length}
          collapsed={spacesCollapsed}
          onToggle={() => setSpacesCollapsed((v) => !v)}
          extra={
            <button
              type="button"
              className="sidebar-icon-btn"
              onClick={() => setCreateDialogOpen(true)}
              title="新建空间"
              aria-label="新建空间"
            >
              <i className="fa-solid fa-plus" />
            </button>
          }
        >
          <ul className="sidebar-workspace-list">
            {workspaces.map((ws) => (
              <WorkspaceGroup
                key={ws.id}
                workspace={ws}
                activeChatId={activeChatId}
                batchMode={batchMode}
                checkedIds={checkedIds}
                renamingChatId={renamingChatId}
                renamingWorkspace={renamingWorkspaceId === ws.id}
                collapsed={collapsedWorkspaces.has(ws.id)}
                onToggleCollapse={(workspaceId) =>
                  setCollapsedWorkspaces((prev) => {
                    const next = new Set(prev);
                    if (next.has(workspaceId)) {
                      next.delete(workspaceId);
                    } else {
                      next.add(workspaceId);
                    }
                    return next;
                  })
                }
                onToggleCheck={toggleCheck}
                onChatOpenMenu={(chat, anchor) =>
                  setChatMenu({ anchor, chat })
                }
                onChatArchive={(chat) => void handleArchiveChat(chat)}
                onChatTogglePin={(chat) => void handleTogglePin(chat)}
                onWorkspaceContextMenu={(e, workspace) =>
                  setWsMenu({ anchor: anchorOf(e), ws: workspace })
                }
                onRenamingChange={(chatId, renaming) =>
                  setRenamingChatId(renaming ? chatId : null)
                }
                onRenamed={(chatId, name) => void handleRenamed(chatId, name)}
                onWorkspaceRenamingChange={(workspaceId, editing) =>
                  setRenamingWorkspaceId(editing ? workspaceId : null)
                }
                onWorkspaceRenamed={(workspaceId, name) =>
                  void handleWsRenamed(workspaceId, name)
                }
              />
            ))}
            {workspaces.length === 0 && (
              <li className="workspace-empty">
                还没有空间，点击空间标题右侧 + 注册一个磁盘目录
              </li>
            )}
          </ul>
        </SidebarSection>
      </div>

      {/* Chat context menu (six entries) */}
      <SessionContextMenu
        anchor={chatMenu?.anchor ?? null}
        chatName={menuChat?.name ?? ""}
        onClose={() => setChatMenu(null)}
        onBatchMode={() => {
          setBatchMode(true);
          setCheckedIds(new Set());
        }}
        onOpenFolder={() => menuChat && openFolderOfChat(menuChat)}
        onRename={() =>
          menuChat && setRenamingChatId(menuChat.id)
        }
        onSaveToWorkspace={() =>
          menuChat && setPickerChatIds([menuChat.id])
        }
        onShare={() => menuChat && void handleShare(menuChat)}
        onDelete={() => menuChat && setDeleteChat(menuChat)}
      />

      {/* Workspace folder context menu */}
      <ContextMenu
        anchor={wsMenu?.anchor ?? null}
        entries={wsMenu ? wsMenuEntries(wsMenu.ws) : []}
        onClose={() => setWsMenu(null)}
      />

      {/* Modals */}
      <WorkspaceDialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onCreated={async (ws) => {
          setCreateDialogOpen(false);
          await useChatsStore.getState().reload();
          toast.success(`空间「${ws.name}」已创建`);
        }}
      />

      <WorkspacePickerModal
        open={pickerChatIds !== null}
        chatIds={pickerChatIds ?? []}
        workspaces={workspaces}
        onClose={() => setPickerChatIds(null)}
        onApplied={async (message) => {
          setPickerChatIds(null);
          await useChatsStore.getState().reload();
          toast.success(message);
        }}
      />

      <OpenFolderModal
        open={folderModal !== null}
        path={folderModal?.path ?? ""}
        hint={folderModal?.hint}
        onClose={() => setFolderModal(null)}
      />

      <Modal
        open={deleteChat !== null}
        title="删除任务"
        onClose={() => setDeleteChat(null)}
        width={420}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setDeleteChat(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => void handleRemoveChat()}
            >
              删除
            </button>
          </>
        }
      >
        <p>
          确定删除任务「{deleteChat?.name || "新任务"}」？
        </p>
        <p className="modal-hint">仅删除会话记录，工作空间磁盘文件不受影响。</p>
      </Modal>

      <Modal
        open={deleteWorkspace !== null}
        title="删除空间"
        onClose={() => setDeleteWorkspace(null)}
        width={420}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setDeleteWorkspace(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => void handleRemoveWorkspace()}
            >
              删除
            </button>
          </>
        }
      >
        <p>确定删除空间「{deleteWorkspace?.name ?? ""}」？</p>
        <p className="modal-hint">
          仅删除空间登记，绑定任务回到任务区；磁盘目录与文件不会被删除。
        </p>
      </Modal>

      <Modal
        open={batchConfirmDelete}
        title="批量删除"
        onClose={() => setBatchConfirmDelete(false)}
        width={420}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setBatchConfirmDelete(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => void runBatchDelete()}
            >
              删除
            </button>
          </>
        }
      >
        <p>确定删除选中的 {checkedIds.size} 个任务？</p>
        <p className="modal-hint">仅删除会话记录，工作空间磁盘文件不受影响。</p>
      </Modal>
    </>
  );
}
