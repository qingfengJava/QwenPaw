/**
 * OpenFolderModal — fallback when the host explorer cannot be launched
 * (remote/headless deployments return 409 from open-folder) or when the
 * chat is not bound to any workspace.
 *
 * Shows the absolute path with one-click copy and an embedded DirBrowser
 * for in-app directory browsing.
 */
import { useEffect, useState } from "react";
import Modal from "../Modal";
import { useToast } from "../Toast";
import DirBrowser from "../workspace/DirBrowser";

export interface OpenFolderModalProps {
  open: boolean;
  /** Absolute directory path; empty = unbound chat (default-dir hint). */
  path: string;
  /** Extra explanation line (e.g. unbound-chat fallback wording). */
  hint?: string;
  onClose: () => void;
}

export default function OpenFolderModal({
  open,
  path,
  hint,
  onClose,
}: OpenFolderModalProps) {
  const toast = useToast();
  const [current, setCurrent] = useState(path);

  // Re-seed whenever the modal targets another directory.
  useEffect(() => {
    setCurrent(path);
  }, [path]);

  const shown = current || path;

  const copy = () => {
    if (!shown) return;
    void navigator.clipboard
      .writeText(shown)
      .then(() => toast.success("路径已复制"))
      .catch(() => toast.error("复制失败，请手动选择复制"));
  };

  return (
    <Modal
      open={open}
      title="打开文件夹"
      onClose={onClose}
      width={560}
      footer={
        <button type="button" className="btn-plain" onClick={onClose}>
          关闭
        </button>
      }
    >
      {hint && <div className="open-folder-hint">{hint}</div>}

      {shown ? (
        <>
          <div className="open-folder-path-row">
            <code className="open-folder-path" title={shown}>
              {shown}
            </code>
            <button type="button" className="btn-plain" onClick={copy}>
              <i className="fa-regular fa-copy" />
              复制路径
            </button>
          </div>
          <div className="open-folder-browser">
            <DirBrowser
              key={path}
              initialPath={path}
              onSelect={(selected) => setCurrent(selected)}
              confirmLabel="使用该目录路径"
            />
          </div>
        </>
      ) : (
        <div className="open-folder-hint">
          该任务未绑定工作空间，Agent 生成的文件保存在默认工作目录中。
          可通过右键菜单「保存到工作空间」绑定一个磁盘目录。
        </div>
      )}
    </Modal>
  );
}
