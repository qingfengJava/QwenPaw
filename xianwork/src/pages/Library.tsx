/**
 * Library — org/project knowledge & files entry. The first release
 * surfaces the file tree via the existing /api/files plane and KB via
 * /api/kb; full dual-scope browsing is a follow-up.
 */
import { useCallback, useEffect, useState } from "react";
import { message, Table, Tag } from "antd";
import { request } from "../api/request";

interface FileEntry {
  name: string;
  path: string;
  is_dir?: boolean;
  size?: number;
  modified?: string;
}

export default function LibraryPage() {
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
      message.error(`加载资料库失败：${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="xian-page">
      <div className="xian-page-title">资料库</div>
      <div className="xian-page-sub">
        团队资料与知识库（组织 / 项目两级，权限随成员角色）
      </div>
      <Table<FileEntry>
        rowKey="path"
        loading={loading}
        dataSource={files}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: "名称",
            dataIndex: "name",
            render: (name: string, row) =>
              row.is_dir ? `📁 ${name}` : `📄 ${name}`,
          },
          {
            title: "类型",
            dataIndex: "is_dir",
            render: (v: boolean) => <Tag>{v ? "目录" : "文件"}</Tag>,
          },
          {
            title: "修改时间",
            dataIndex: "modified",
            render: (v: string) => v?.slice(0, 19)?.replace("T", " ") || "—",
          },
        ]}
      />
    </div>
  );
}
