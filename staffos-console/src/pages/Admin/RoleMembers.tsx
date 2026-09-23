/**
 * RoleMembers — 角色-员工列表 tab（企业级 RBAC 角色工作台）。
 *
 * 展示持有某角色的员工，支持关键字搜索、添加员工（穿梭框选未持有该角色的
 * 用户）、批量移除。数据源为 GET /admin/roles/{name}/users；增删复用
 * /admin/users/{u}/roles 端点。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Input,
  Modal,
  Popconfirm,
  Table,
  Transfer,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminRolesApi, adminUsersApi } from "../../api/modules/admin";
import type { AdminUserView, RoleMemberView } from "../../api/modules/admin";
import styles from "./admin.module.less";

interface RoleMembersProps {
  roleName: string | null;
}

function RoleMembers({ roleName }: RoleMembersProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [members, setMembers] = useState<RoleMemberView[]>([]);
  const [allUsers, setAllUsers] = useState<AdminUserView[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [addTargetKeys, setAddTargetKeys] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!roleName) return;
    setLoading(true);
    try {
      const [memberList, userList] = await Promise.all([
        adminRolesApi.listUsers(roleName),
        adminUsersApi.list().catch(() => [] as AdminUserView[]),
      ]);
      setMembers(memberList);
      setAllUsers(userList);
      setSelectedRowKeys([]);
    } catch (err) {
      console.error(err);
      message.error(t("admin.roles.membersLoadFailed", "加载角色成员失败"));
    } finally {
      setLoading(false);
    }
  }, [roleName, message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const memberNames = useMemo(
    () => new Set(members.map((m) => m.username)),
    [members],
  );

  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    if (!needle) return members;
    return members.filter(
      (m) =>
        `${m.real_name} ${m.phone} ${m.username} ${m.display_name}`
          .toLowerCase()
          .includes(needle),
    );
  }, [members, keyword]);

  const openAdd = () => {
    setAddTargetKeys([]);
    setAddOpen(true);
  };

  const submitAdd = async () => {
    if (!roleName || !addTargetKeys.length) {
      setAddOpen(false);
      return;
    }
    setSaving(true);
    try {
      for (const username of addTargetKeys) {
        // eslint-disable-next-line no-await-in-loop
        await adminUsersApi.grantRole(username, roleName);
      }
      message.success(t("admin.roles.membersAdded", "员工已添加"));
      setAddOpen(false);
      load();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  const removeOne = async (username: string) => {
    if (!roleName) return;
    try {
      await adminUsersApi.revokeRole(username, roleName);
      message.success(t("admin.roles.memberRemoved", "已移除"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const batchRemove = async () => {
    if (!roleName) return;
    try {
      for (const username of selectedRowKeys) {
        // eslint-disable-next-line no-await-in-loop
        await adminUsersApi.revokeRole(username, roleName);
      }
      message.success(t("admin.roles.membersRemoved", "已批量移除"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const columns: ColumnsType<RoleMemberView> = [
    {
      title: t("admin.org.colName", "姓名"),
      dataIndex: "real_name",
      align: "center",
      render: (_: string, m) => m.real_name || m.display_name || m.username,
    },
    {
      title: t("admin.org.colPhone", "手机号"),
      dataIndex: "phone",
      align: "center",
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.org.colAccount", "登录账号"),
      dataIndex: "username",
      align: "center",
    },
    {
      title: t("admin.org.colDept", "部门"),
      dataIndex: "department_names",
      align: "center",
      render: (names: string[]) => (names || []).join("、") || "—",
    },
    {
      title: t("admin.org.colStatus", "状态"),
      dataIndex: "disabled",
      align: "center",
      width: 90,
      render: (disabled: boolean) => (
        <span className={disabled ? styles.toneGray : styles.toneGreen}>
          {disabled
            ? t("admin.org.disabled", "禁用")
            : t("admin.org.enabled", "启用")}
        </span>
      ),
    },
    {
      title: t("common.actions", "操作"),
      key: "actions",
      align: "center",
      width: 100,
      render: (_: unknown, m) => (
        <Popconfirm
          title={t("admin.roles.removeConfirm", "移除该员工的此角色？")}
          onConfirm={() => removeOne(m.username)}
        >
          <Button type="link" size="small" danger>
            {t("common.remove", "移除")}
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const transferData = allUsers.map((u) => ({
    key: u.username,
    title: u.real_name || u.display_name || u.username,
    description: u.phone || u.username,
    disabled: memberNames.has(u.username),
  }));

  return (
    <div className={styles.fadeIn}>
      <div className={styles.filterBar}>
        <div className={styles.filterBarGroup}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            {t("admin.roles.addEmployee", "添加员工")}
          </Button>
          <Button
            danger
            disabled={!selectedRowKeys.length}
            onClick={batchRemove}
          >
            {t("admin.roles.batchRemove", "批量移除")}
          </Button>
        </div>
        <Input
          style={{ width: 240 }}
          placeholder={t("admin.org.searchMember", "姓名/手机号/登录账号")}
          prefix={<SearchOutlined />}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
        />
      </div>

      <Table<RoleMemberView>
        rowKey="username"
        loading={loading}
        dataSource={filtered}
        columns={columns}
        style={{ marginTop: 12 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        locale={{ emptyText: t("admin.roles.noMembers", "该角色暂无员工") }}
      />

      <Modal
        title={t("admin.roles.addEmployee", "添加员工")}
        open={addOpen}
        onOk={submitAdd}
        onCancel={() => setAddOpen(false)}
        confirmLoading={saving}
        width={640}
        destroyOnHidden
      >
        <Transfer
          showSearch
          dataSource={transferData}
          targetKeys={addTargetKeys}
          onChange={(keys) => setAddTargetKeys(keys as string[])}
          render={(item) => `${item.title}${item.description ? ` (${item.description})` : ""}`}
          titles={[
            t("admin.roles.availableUsers", "可选用户"),
            t("admin.roles.toAdd", "待添加"),
          ]}
          listStyle={{ width: 260, height: 360 }}
        />
      </Modal>
    </div>
  );
}

export default RoleMembers;
