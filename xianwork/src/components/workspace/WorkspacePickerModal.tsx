/**
 * WorkspacePickerModal —「保存到工作空间」(competitor shot 4).
 *
 * Three selection paths feeding one read-only path bar (clearable ×):
 * the recent-workspaces list, the embedded DirBrowser, or「继承 Agent
 * 默认目录」(unbind semantics). The orange 应用 button binds the target
 * chats to a registered workspace; a freshly browsed path is registered
 * first (name defaults to the directory basename; 409 = already
 * registered → refresh the list and pick it there).
 *
 * Both entry points (single chat context menu, future batch flows) reuse
 * this component — `chatIds` is always a list.
 */
import { useMemo, useState } from "react";
import Modal from "../Modal";
import { workspaceApi } from "../../api/modules";
import type { WorkspaceView } from "../../api/modules";
import DirBrowser from "./DirBrowser";

export interface WorkspacePickerModalProps {
  open: boolean;
  /** Target chats of the bind/unbind action. */
  chatIds: string[];
  /** Current workspaces with nested chats (from the shared store). */
  workspaces: WorkspaceView[];
  onClose: () => void;
  /** Fired once per applied action; parent refreshes + toasts. */
  onApplied: (message: string) => void;
}

function dirBaseName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const base = trimmed.split(/[\\/]/).pop() ?? "";
  return base || trimmed || "新空间";
}

export default function WorkspacePickerModal({
  open,
  chatIds,
  workspaces,
  onClose,
  onApplied,
}: WorkspacePickerModalProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manualPath, setManualPath] = useState<string | null>(null);
  const [inherit, setInherit] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedWs = useMemo(
    () => workspaces.find((w) => w.id === selectedId) ?? null,
    [workspaces, selectedId],
  );
  const pathBar = inherit
    ? "（继承 Agent 默认目录）"
    : (manualPath ?? selectedWs?.dir_path ?? "");

  /** Chat → its current workspace (id lookup only; paths stay server-side). */
  const boundWorkspaceOf = (chatId: string): WorkspaceView | null =>
    workspaces.find((w) => (w.chats ?? []).some((c) => c.id === chatId)) ?? null;

  const reset = () => {
    setSelectedId(null);
    setManualPath(null);
    setInherit(false);
    setBrowsing(false);
    setSubmitting(false);
    setError(null);
  };

  const close = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const applyDisabled =
    submitting || (!inherit && !selectedWs && !manualPath?.trim());

  const applyLabel = inherit
    ? "恢复默认目录"
    : selectedWs
      ? "应用"
      : "注册并绑定";

  const apply = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (inherit) {
        // Unbind every chat that currently sits in a workspace.
        let unbound = 0;
        for (const chatId of chatIds) {
          const ws = boundWorkspaceOf(chatId);
          if (!ws) continue;
          await workspaceApi.unbindChat(ws.id, chatId);
          unbound += 1;
        }
        reset();
        onApplied(
          unbound > 0
            ? `已恢复 ${unbound} 个任务的 Agent 默认目录`
            : "任务本就未绑定工作空间",
        );
        return;
      }
      if (selectedWs) {
        const r = await workspaceApi.bindChats(selectedWs.id, chatIds);
        const name = selectedWs.name;
        reset();
        onApplied(`已保存到「${name}」（绑定 ${r.bound} 个任务）`);
        return;
      }
      const path = (manualPath ?? "").trim();
      if (!path) {
        setError("请先选择一个空间或目录");
        setSubmitting(false);
        return;
      }
      try {
        const ws = await workspaceApi.create({
          name: dirBaseName(path),
          dir_path: path,
        });
        await workspaceApi.bindChats(ws.id, chatIds);
        reset();
        onApplied(`已创建空间「${ws.name}」并绑定任务`);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (/already registered|已注册/i.test(message)) {
          setError("该目录已是注册空间（列表已刷新，请从最近项目中选择）");
        } else {
          setError(message);
        }
        setSubmitting(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="保存到工作空间"
      onClose={close}
      width={560}
      footer={
        <>
          <button type="button" className="btn-plain" onClick={close} disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            className="btn-accent"
            onClick={() => void apply()}
            disabled={applyDisabled}
          >
            {submitting ? "应用中…" : applyLabel}
          </button>
        </>
      }
    >
      <div className="form-field">
        <label>项目路径</label>
        <div className="picker-path-row">
          <input value={pathBar} readOnly placeholder="从下方选择空间或浏览目录" />
          <button
            type="button"
            className="icon-btn"
            aria-label="清空路径"
            disabled={inherit || (!manualPath && !selectedWs)}
            onClick={() => {
              setSelectedId(null);
              setManualPath(null);
              setError(null);
            }}
          >
            <i className="fa-solid fa-xmark" />
          </button>
        </div>
      </div>

      <div className="form-field">
        <label>最近项目（我的空间）</label>
        <ul className="picker-recent-list">
          {workspaces.map((ws) => (
            <li key={ws.id}>
              <button
                type="button"
                className={`picker-recent-item${selectedId === ws.id ? " selected" : ""}`}
                onClick={() => {
                  setSelectedId(ws.id);
                  setManualPath(null);
                  setInherit(false);
                  setError(null);
                }}
              >
                <i className="fa-regular fa-folder" />
                <span className="picker-recent-name">{ws.name}</span>
                <span className="picker-recent-path" title={ws.dir_path}>
                  {ws.dir_path}
                </span>
              </button>
            </li>
          ))}
          {workspaces.length === 0 && (
            <li className="dir-browser-empty">还没有空间，可浏览目录后注册</li>
          )}
        </ul>
      </div>

      <div className="form-field">
        <button
          type="button"
          className="btn-plain"
          onClick={() => setBrowsing((v) => !v)}
        >
          <i className="fa-regular fa-folder-open" />
          {browsing ? "收起目录浏览" : "浏览目录…"}
        </button>
      </div>

      {browsing && (
        <DirBrowser
          confirmLabel="选定该目录"
          onSelect={(path) => {
            setManualPath(path);
            setSelectedId(null);
            setInherit(false);
            setBrowsing(false);
            setError(null);
          }}
        />
      )}

      <button
        type="button"
        className={`picker-inherit${inherit ? " on" : ""}`}
        onClick={() => {
          setInherit((v) => !v);
          setError(null);
        }}
      >
        <i className="fa-solid fa-arrow-rotate-left" />
        继承 Agent 默认目录（解除绑定）
      </button>

      {error && <div className="modal-error">{error}</div>}
    </Modal>
  );
}
