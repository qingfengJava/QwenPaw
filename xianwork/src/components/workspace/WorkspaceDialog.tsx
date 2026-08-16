/**
 * WorkspaceDialog — register a new workspace (「新建空间」).
 *
 * Name + absolute directory path (typed manually or picked through the
 * embedded DirBrowser). The optional "create missing directory" checkbox
 * maps to the backend `create=true` mkdir flag; without it the server
 * requires an existing directory.
 */
import { useState } from "react";
import Modal from "../Modal";
import { workspaceApi } from "../../api/modules";
import type { WorkspaceView } from "../../api/modules";
import DirBrowser from "./DirBrowser";

export interface WorkspaceDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (ws: WorkspaceView) => void;
}

export default function WorkspaceDialog({
  open,
  onClose,
  onCreated,
}: WorkspaceDialogProps) {
  const [name, setName] = useState("");
  const [dirPath, setDirPath] = useState("");
  const [createDir, setCreateDir] = useState(true);
  const [browsing, setBrowsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setName("");
    setDirPath("");
    setCreateDir(true);
    setBrowsing(false);
    setSubmitting(false);
    setError(null);
  };

  const close = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const submit = async () => {
    const trimmedName = name.trim();
    const trimmedDir = dirPath.trim();
    if (!trimmedName || !trimmedDir) {
      setError("请填写空间名称和目录路径");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const ws = await workspaceApi.create({
        name: trimmedName,
        dir_path: trimmedDir,
        create: createDir,
      });
      reset();
      onCreated(ws);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(
        /already registered|已注册/i.test(message)
          ? "该目录已注册为工作空间"
          : message,
      );
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="新建空间"
      onClose={close}
      width={520}
      footer={
        <>
          <button type="button" className="btn-plain" onClick={close} disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            className="btn-black"
            onClick={() => void submit()}
            disabled={submitting || !name.trim() || !dirPath.trim()}
          >
            {submitting ? "创建中…" : "创建"}
          </button>
        </>
      }
    >
      <div className="form-field">
        <label htmlFor="workspace-name">空间名称</label>
        <input
          id="workspace-name"
          value={name}
          maxLength={60}
          placeholder="例如：市场部项目文件"
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div className="form-field">
        <label htmlFor="workspace-dir">磁盘目录（绝对路径）</label>
        <div className="workspace-dir-row">
          <input
            id="workspace-dir"
            value={dirPath}
            placeholder="D:\\projects\\my-workspace"
            onChange={(e) => setDirPath(e.target.value)}
          />
          <button
            type="button"
            className="btn-plain"
            onClick={() => setBrowsing((v) => !v)}
          >
            <i className="fa-regular fa-folder-open" />
            {browsing ? "收起浏览" : "浏览…"}
          </button>
        </div>
        <p className="form-hint">
          Agent 生成的文件与上传的媒体将保存到该目录（media 子目录）。
        </p>
      </div>

      {browsing && (
        <DirBrowser
          onSelect={(path) => {
            setDirPath(path);
            setBrowsing(false);
          }}
        />
      )}

      <label className="dialog-check">
        <input
          type="checkbox"
          checked={createDir}
          onChange={(e) => setCreateDir(e.target.checked)}
        />
        <span>目录不存在时自动创建</span>
      </label>

      {error && <div className="modal-error">{error}</div>}
    </Modal>
  );
}
