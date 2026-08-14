/**
 * Library — org/project knowledge & files entry via the /api/files plane.
 * Extension design: PageShell + list-row cards (no antd Table).
 */
import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import { useToast } from "../components/Toast";
import { request } from "../api/request";

interface FileEntry {
  name: string;
  path: string;
  is_dir?: boolean;
  size?: number;
  modified?: string;
}

function formatSize(size?: number): string {
  if (size == null) {
    return "—";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function LibraryPage() {
  const toast = useToast();
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<FileEntry[] | { files?: FileEntry[] }>(
        "/files",
      );
      setFiles(Array.isArray(data) ? data : (data.files ?? []));
    } catch (err) {
      toast.error(`加载资料库失败：${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="view active">
      <PageShell
        title="资料库"
        subtitle="团队资料与知识库（组织 / 项目两级，权限随成员角色）"
      >
        {loading && <div className="blank-state">加载中…</div>}
        {!loading && files.length === 0 && (
          <div className="blank-state">
            <i
              className="fa-regular fa-folder-open"
              style={{ fontSize: 26, marginBottom: 10 }}
            />
            <div>资料库还是空的，上传的第一份团队资料将出现在这里</div>
          </div>
        )}
        {files.map((file) => (
          <div key={file.path} className="list-row-card">
            <div className="list-row-main">
              <div
                className="card-icon"
                style={{ width: 36, height: 36, fontSize: 14, marginBottom: 0 }}
              >
                <i
                  className={
                    file.is_dir ? "fa-solid fa-folder" : "fa-regular fa-file-lines"
                  }
                />
              </div>
              <div>
                <div className="list-row-title">{file.name}</div>
                <div className="list-row-desc">{file.path}</div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="task-status">
                {file.is_dir ? "目录" : formatSize(file.size)}
              </span>
              <span className="task-time">
                {file.modified?.slice(0, 16)?.replace("T", " ") ?? ""}
              </span>
            </div>
          </div>
        ))}
      </PageShell>
    </div>
  );
}
