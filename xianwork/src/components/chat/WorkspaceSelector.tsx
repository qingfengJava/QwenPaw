/**
 * WorkspaceSelector — composer-embedded workspace picker (competitor shot
 * parity): trigger + bottom-anchored panel with search, a 默认任务区
 * (unbound) entry, the registered workspace list, and two register
 * shortcuts (新建工作空间 / 打开本地文件夹).
 *
 * Binding modes:
 *   - chatId set (Chat page): choices go through the chats store —
 *     selecting a workspace is a plain bind (backend set_project_dir
 *     overwrites, no unbind needed), 默认任务区 unbinds. Running chats
 *     get 409 → friendly toast.
 *   - no chatId (Home launcher): the pick parks in
 *     chatPrefs.pendingWorkspaceId and Home applies it right after the
 *     chat is created.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { workspaceApi, type WorkspaceView } from "../../api/modules";
import { useChatsStore } from "../../stores/chats";
import { useChatPrefs } from "../../stores/chatPrefs";
import { friendlyWorkspaceError } from "../../lib/workspaceErrors";
import { useToast } from "../Toast";
import WorkspaceDialog from "../workspace/WorkspaceDialog";

/** Last path segment of a Windows/POSIX directory path, for auto-naming. */
function dirBasename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export default function WorkspaceSelector({
  chatId,
  disabled,
}: {
  /** Bound chat (Chat page); omit on Home to park a pending selection. */
  chatId?: string;
  /** Streaming guard — rebinding a running chat is rejected with 409. */
  disabled?: boolean;
}) {
  const toast = useToast();
  const workspaces = useChatsStore((s) => s.workspaces);
  const reload = useChatsStore((s) => s.reload);
  const bindChats = useChatsStore((s) => s.bindChats);
  const unbindChat = useChatsStore((s) => s.unbindChat);
  const pendingWorkspaceId = useChatPrefs((s) => s.pendingWorkspaceId);
  const setPendingWorkspace = useChatPrefs((s) => s.setPendingWorkspace);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  /** Which workspace the chat currently lives in (server-side grouping). */
  const bound = useMemo(
    () =>
      workspaces.find((w) =>
        !!chatId && (w.chats ?? []).some((c) => c.id === chatId),
      ),
    [workspaces, chatId],
  );

  /** Effective selection: live binding on the Chat page, pending on Home. */
  const selected = chatId
    ? (bound ?? null)
    : (workspaces.find((w) => w.id === pendingWorkspaceId) ?? null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(
      (w) =>
        w.name.toLowerCase().includes(q) ||
        w.dir_path.toLowerCase().includes(q),
    );
  }, [workspaces, query]);

  const applyChoice = async (ws: WorkspaceView | null) => {
    setOpen(false);
    if (!chatId) {
      setPendingWorkspace(ws?.id ?? null);
      return;
    }
    if (!ws) {
      if (!bound) return;
      try {
        await unbindChat(bound.id, chatId);
      } catch (err) {
        toast.error(friendlyWorkspaceError(err, "移出工作空间失败"));
      }
      return;
    }
    try {
      await bindChats(ws.id, [chatId]);
    } catch (err) {
      toast.error(friendlyWorkspaceError(err, "切换工作空间失败"));
    }
  };

  /** 打开本地文件夹: native picker → register → select in one flow. */
  const openLocalFolder = async () => {
    if (opening) return;
    setOpening(true);
    try {
      const picked = await workspaceApi.pickDirectory();
      if (!picked.path) return; // user cancelled the OS dialog
      const ws = await workspaceApi.create({
        name: dirBasename(picked.path),
        dir_path: picked.path,
        create: false,
      });
      await reload();
      await applyChoice(ws);
      toast.success(`已添加工作空间「${ws.name}」`);
    } catch (err) {
      toast.error(friendlyWorkspaceError(err, "打开本地文件夹失败"));
    } finally {
      setOpening(false);
    }
  };

  const renderOption = (ws: WorkspaceView) => {
    const isActive = !!selected && selected.id === ws.id;
    return (
      <button
        type="button"
        key={ws.id}
        className={`ws-option${isActive ? " active" : ""}`}
        onClick={() => void applyChoice(ws)}
      >
        <i className="fa-regular fa-folder" />
        <span className="ws-option-copy">
          <span className="ws-option-name">{ws.name}</span>
          <span className="ws-option-path" title={ws.dir_path}>
            {ws.dir_path}
          </span>
        </span>
        {isActive && <i className="fa-solid fa-circle-check ms-check" />}
      </button>
    );
  };

  const isDefault = !selected;

  return (
    <div className="ws-selector" ref={rootRef}>
      <button
        type="button"
        className={`ws-trigger${!isDefault ? " accent" : ""}${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title={
          disabled
            ? "回复中的任务暂不能切换工作空间"
            : selected
              ? `工作空间：${selected.name}`
              : "选择工作空间"
        }
        aria-label="选择工作空间"
      >
        <i className="fa-regular fa-folder" />
        <span>{selected ? selected.name : "选择工作空间"}</span>
        <i className="fa-solid fa-chevron-down ms-caret" />
      </button>

      {open && (
        <div className="ws-panel">
          <div className="ws-search">
            <i className="fa-solid fa-magnifying-glass" />
            <input
              type="text"
              value={query}
              placeholder="搜索工作空间"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <button
            type="button"
            className={`ws-option${isDefault ? " active" : ""}`}
            onClick={() => void applyChoice(null)}
          >
            <i className="fa-solid fa-inbox" />
            <span className="ws-option-copy">
              <span className="ws-option-name">默认任务区</span>
              <span className="ws-option-path">不绑定任何工作空间</span>
            </span>
            {isDefault && <i className="fa-solid fa-circle-check ms-check" />}
          </button>

          {filtered.length > 0 && <div className="ws-group-label">工作空间</div>}
          {filtered.map(renderOption)}
          {!query.trim() && workspaces.length === 0 && (
            <div className="ws-empty">还没有工作空间，先新建一个吧</div>
          )}
          {query.trim() && filtered.length === 0 && (
            <div className="ws-empty">没有匹配的工作空间</div>
          )}

          <div className="ws-divider" />
          <button
            type="button"
            className="ws-action"
            onClick={() => {
              setOpen(false);
              setDialogOpen(true);
            }}
          >
            <i className="fa-solid fa-plus" />
            <span>新建工作空间</span>
          </button>
          <button
            type="button"
            className="ws-action"
            disabled={opening}
            onClick={() => void openLocalFolder()}
          >
            <i
              className={
                opening
                  ? "fa-solid fa-spinner fa-spin"
                  : "fa-solid fa-folder-open"
              }
            />
            <span>{opening ? "正在选择目录…" : "打开本地文件夹"}</span>
          </button>
        </div>
      )}

      <WorkspaceDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={(ws) => {
          setDialogOpen(false);
          void (async () => {
            await reload();
            await applyChoice(ws);
            toast.success(`已添加工作空间「${ws.name}」`);
          })();
        }}
      />
    </div>
  );
}
