/**
 * InviteModal — the「邀请」drawer (prototype top-nav button): org
 * directory search (跨部门), current members with role selects, and
 * add/remove via the existing members API.
 */
import { useEffect, useState } from "react";
import Modal from "../Modal";
import Avatar from "../Avatar";
import { useToast } from "../Toast";
import { directoryApi, projectApi } from "../../api/modules";
import type {
  DirectoryUser,
  ProjectMember,
} from "../../api/modules";

const ROLE_LABEL: Record<string, string> = {
  owner: "拥有者",
  editor: "可编辑",
  viewer: "仅查看",
};

export interface InviteModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  canManage: boolean;
  members: ProjectMember[];
  onChanged: () => void;
}

export default function InviteModal({
  open,
  onClose,
  projectId,
  canManage,
  members,
  onChanged,
}: InviteModalProps) {
  const toast = useToast();
  const [keyword, setKeyword] = useState("");
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    directoryApi
      .users(keyword)
      .then(setDirectory)
      .catch(() => setDirectory([]));
  }, [open, keyword]);

  const memberNames = new Set(members.map((m) => m.username));

  const invite = async (user: DirectoryUser, role: string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      await projectApi.addMember(projectId, user.username, role);
      toast.success(`已邀请 ${user.display_name}`);
      onChanged();
    } catch (err) {
      toast.error(String(err));
    } finally {
      setBusy(false);
    }
  };

  const setRole = async (username: string, role: string) => {
    try {
      await projectApi.updateMemberRole(projectId, username, role);
      toast.success("角色已更新");
      onChanged();
    } catch (err) {
      toast.error(String(err));
    }
  };

  const removeMember = async (username: string) => {
    try {
      await projectApi.removeMember(projectId, username);
      toast.success("已移出项目");
      onChanged();
    } catch (err) {
      toast.error(String(err));
    }
  };

  return (
    <Modal open={open} title="邀请成员" onClose={onClose} width={520}>
      <div className="search-input-box" style={{ width: "100%" }}>
        <i className="fa-solid fa-magnifying-glass" />
        <input
          style={{ width: "100%" }}
          placeholder="搜索姓名 / 用户名，跨部门邀请"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      <div className="directory-list">
        {directory
          .filter((user) => !memberNames.has(user.username))
          .slice(0, 8)
          .map((user) => (
            <div key={user.username} className="member-row">
              <div className="member-row-left">
                <Avatar name={user.display_name} size={28} />
                <div>
                  <div className="member-row-name">{user.display_name}</div>
                  <div className="member-row-dept">
                    {user.department_name || "未分配部门"} · {user.username}
                  </div>
                </div>
              </div>
              {canManage ? (
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn-plain"
                    style={{ padding: "5px 12px", fontSize: 12 }}
                    onClick={() => void invite(user, "editor")}
                  >
                    邀请 · 可编辑
                  </button>
                  <button
                    type="button"
                    className="btn-plain"
                    style={{ padding: "5px 12px", fontSize: 12 }}
                    onClick={() => void invite(user, "viewer")}
                  >
                    仅查看
                  </button>
                </div>
              ) : (
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  需要拥有者权限
                </span>
              )}
            </div>
          ))}
        {directory.filter((user) => !memberNames.has(user.username)).length ===
          0 && (
          <div className="blank-state" style={{ padding: "24px 0" }}>
            没有可邀请的同事
          </div>
        )}
      </div>

      <div className="asset-group-heading" style={{ marginTop: 16 }}>
        项目成员（{members.length}）
      </div>
      {members.map((member) => (
        <div key={member.username} className="member-row">
          <div className="member-row-left">
            <Avatar name={member.username} size={28} />
            <div className="member-row-name">{member.username}</div>
          </div>
          {member.role === "owner" ? (
            <span className="member-row-dept">{ROLE_LABEL[member.role]}</span>
          ) : canManage ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select
                className="native-select member-role-select"
                value={member.role}
                onChange={(e) => void setRole(member.username, e.target.value)}
              >
                <option value="editor">可编辑</option>
                <option value="viewer">仅查看</option>
              </select>
              <button
                type="button"
                className="icon-btn"
                title="移出项目"
                onClick={() => void removeMember(member.username)}
              >
                <i className="fa-solid fa-xmark" />
              </button>
            </div>
          ) : (
            <span className="member-row-dept">{ROLE_LABEL[member.role]}</span>
          )}
        </div>
      ))}
    </Modal>
  );
}
