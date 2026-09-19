/**
 * Admin/Organization — 部门员工管理工作台（企业级 RBAC 升级）。
 *
 * 左栏：部门树（搜索 + 悬停增删改）；右栏：所选部门的员工列表
 * （状态分段筛选 + 关键字搜索 + 添加成员 / 调整部门 / 批量移出）。
 * 员工归属部门、角色分配均与后端 PG 权威平面联动，视觉遵循 --pg-* token。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Avatar,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Table,
  Tooltip,
  Tree,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { ColumnsType } from "antd/es/table";
import {
  ApartmentOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SwapOutlined,
  UserAddOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { HasPerm } from "@/components/HasPerm";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminOrgsApi, adminUsersApi, adminRolesApi } from "../../api/modules/admin";
import type {
  AdminUserView,
  DepartmentTree,
  OrgRecord,
  RoleRecord,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

const enc = encodeURIComponent;

function avatarFor(user: AdminUserView): string {
  if (user.avatar) return user.avatar;
  // 无自定义头像时按 username 生成 DiceBear 种子（零存储成本）。
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${enc(user.username)}`;
}

function OrganizationPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [orgs, setOrgs] = useState<OrgRecord[]>([]);
  const [tree, setTree] = useState<DepartmentTree[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);

  const [selected, setSelected] = useState<string | null>(null);
  const [treeSearch, setTreeSearch] = useState("");
  const [status, setStatus] = useState<"all" | "enabled" | "disabled">("all");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);

  // 部门 CRUD 弹窗
  const [deptModal, setDeptModal] = useState<{
    open: boolean;
    mode: "create" | "rename";
    deptId?: string;
    parentId?: string | null;
  }>({ open: false, mode: "create" });
  const [deptForm] = Form.useForm();

  // 添加成员弹窗
  const [memberModal, setMemberModal] = useState(false);
  const [memberForm] = Form.useForm();

  // 调整部门弹窗
  const [moveModal, setMoveModal] = useState(false);
  const [moveForm] = Form.useForm();

  const genderLabel = (g: number) =>
    g === 1
      ? t("admin.org.genderMale", "男")
      : g === 2
        ? t("admin.org.genderFemale", "女")
        : t("admin.org.genderUnknown", "未知");

  const roleDisplay = useCallback(
    (name: string) => {
      const r = roles.find((x) => x.name === name);
      return r?.display_name || r?.name || name;
    },
    [roles],
  );

  const loadTree = useCallback(async () => {
    const [treeData, orgList, roleList] = await Promise.all([
      adminOrgsApi.departmentTree().catch(() => [] as DepartmentTree[]),
      adminOrgsApi.listOrgs().catch(() => [] as OrgRecord[]),
      adminRolesApi.list().catch(() => [] as RoleRecord[]),
    ]);
    setTree(treeData);
    setOrgs(orgList);
    setRoles(roleList);
  }, []);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const list = await adminUsersApi.list({
        department_id: selected || undefined,
        disabled: status === "all" ? undefined : status === "disabled",
        keyword: keyword.trim() || undefined,
      });
      setUsers(list);
      setSelectedRowKeys([]);
    } catch (err) {
      console.error(err);
      message.error(t("admin.org.loadFailed", "加载部门员工失败"));
    } finally {
      setLoading(false);
    }
  }, [selected, status, keyword, message, t]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  // 本地过滤部门树：命中节点及其祖先保留。
  const filteredTree = useMemo(() => {
    const needle = treeSearch.trim().toLowerCase();
    if (!needle) return tree;
    const walk = (nodes: DepartmentTree[]): DepartmentTree[] =>
      nodes
        .map((node) => {
          const kids = walk(node.children || []);
          const hit = node.name.toLowerCase().includes(needle);
          if (hit || kids.length) {
            return { ...node, children: kids };
          }
          return null;
        })
        .filter(Boolean) as DepartmentTree[];
    return walk(tree);
  }, [tree, treeSearch]);

  const rootOrgName =
    orgs.find((o) => o.id === "default")?.name ||
    orgs[0]?.name ||
    t("admin.org.rootOrg", "组织");

  const toTreeNodes = useCallback(
    (nodes: DepartmentTree[]): DataNode[] =>
      nodes.map((node) => ({
        key: node.id,
        title: node.name,
        name: node.name,
        children: node.children.length ? toTreeNodes(node.children) : undefined,
      })),
    [],
  );

  const treeData: DataNode[] = useMemo(() => {
    const orgRoot: DataNode = {
      key: "",
      title: rootOrgName,
      children: toTreeNodes(filteredTree),
    };
    return [orgRoot];
  }, [filteredTree, rootOrgName, toTreeNodes]);

  const findDept = useCallback(
    (id: string, nodes: DepartmentTree[]): DepartmentTree | null => {
      for (const node of nodes) {
        if (node.id === id) return node;
        const hit = findDept(id, node.children || []);
        if (hit) return hit;
      }
      return null;
    },
    [],
  );

  const breadcrumb = useMemo(() => {
    if (!selected) return rootOrgName;
    const node = findDept(selected, tree);
    return node ? `${rootOrgName} / ${node.name}` : rootOrgName;
  }, [selected, tree, rootOrgName, findDept]);

  // ── 部门操作 ──────────────────────────────────────────────
  const openCreateDept = (parentId: string | null) => {
    setDeptModal({ open: true, mode: "create", parentId });
    deptForm.resetFields();
  };
  const openRenameDept = (deptId: string, name: string) => {
    setDeptModal({ open: true, mode: "rename", deptId });
    deptForm.setFieldsValue({ name });
  };

  const submitDept = async () => {
    const values = await deptForm.validateFields();
    try {
      if (deptModal.mode === "create") {
        await adminOrgsApi.createDepartment({
          name: values.name,
          parent_id: deptModal.parentId || null,
        });
        message.success(t("admin.org.created", "部门已创建"));
      } else if (deptModal.deptId) {
        await adminOrgsApi.updateDepartment(deptModal.deptId, {
          name: values.name,
        });
        message.success(t("admin.org.renamed", "部门已重命名"));
      }
      setDeptModal({ open: false, mode: "create" });
      loadTree();
    } catch (err) {
      message.error(String(err));
    }
  };

  const deleteDept = async (deptId: string) => {
    try {
      await adminOrgsApi.deleteDepartment(deptId);
      message.success(t("admin.org.deleted", "部门已删除"));
      if (selected === deptId) setSelected(null);
      loadTree();
    } catch (err) {
      message.error(String(err));
    }
  };

  // ── 成员操作 ──────────────────────────────────────────────
  const openAddMember = () => {
    memberForm.resetFields();
    setMemberModal(true);
  };

  const submitMember = async () => {
    const values = await memberForm.validateFields();
    try {
      const created = await adminUsersApi.create({
        username: values.username,
        password: values.password,
        role: values.rbac_role ? "employee" : "employee",
        real_name: values.real_name || "",
        phone: values.phone || "",
        gender: values.gender ?? 0,
        position: values.position || "",
        display_name: values.real_name || "",
        department_ids: selected ? [selected] : values.department_ids || [],
      });
      // 分配 RBAC 角色（可选）。
      if (values.rbac_role && created?.username) {
        await adminUsersApi
          .grantRole(created.username, values.rbac_role)
          .catch(() => undefined);
      }
      message.success(t("admin.org.memberAdded", "成员已添加"));
      setMemberModal(false);
      loadUsers();
      loadTree();
    } catch (err) {
      message.error(String(err));
    }
  };

  const openMove = () => {
    if (!selectedRowKeys.length) {
      message.warning(t("admin.org.pickFirst", "请先勾选成员"));
      return;
    }
    moveForm.resetFields();
    setMoveModal(true);
  };

  const submitMove = async () => {
    const values = await moveForm.validateFields();
    try {
      await adminOrgsApi.moveMembers({
        usernames: selectedRowKeys,
        target_dept_id: values.target_dept_id,
        source_dept_id: selected || null,
      });
      message.success(t("admin.org.moved", "已调整部门"));
      setMoveModal(false);
      loadUsers();
      loadTree();
    } catch (err) {
      message.error(String(err));
    }
  };

  const batchRemove = async () => {
    if (!selected) {
      message.warning(t("admin.org.selectDeptFirst", "请先选择部门"));
      return;
    }
    try {
      await adminOrgsApi.removeMembersBatch(selected, selectedRowKeys);
      message.success(t("admin.org.removedFromDept", "已移出本部门"));
      loadUsers();
      loadTree();
    } catch (err) {
      message.error(String(err));
    }
  };

  const resetFilters = () => {
    setStatus("all");
    setKeyword("");
  };

  const columns: ColumnsType<AdminUserView> = [
    {
      title: t("admin.org.colName", "姓名"),
      dataIndex: "real_name",
      align: "center",
      render: (_: string, user) => (
        <Space>
          <Avatar src={avatarFor(user)} size={24} />
          <span>{user.real_name || user.display_name || user.username}</span>
        </Space>
      ),
    },
    {
      title: t("admin.org.colPhone", "手机号"),
      dataIndex: "phone",
      align: "center",
      render: (v: string) => v || "—",
    },
    {
      title: t("admin.org.colGender", "性别"),
      dataIndex: "gender",
      align: "center",
      width: 80,
      render: (g: number) => genderLabel(g),
    },
    {
      title: t("admin.org.colAccount", "登录账号"),
      dataIndex: "username",
      align: "center",
    },
    {
      title: t("admin.org.colSuper", "超管"),
      dataIndex: "is_superadmin",
      align: "center",
      width: 80,
      render: (v: boolean) =>
        v ? (
          <span className={styles.toneRed}>
            {t("admin.org.superAdmin", "超管")}
          </span>
        ) : null,
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
      title: t("admin.org.colRoles", "角色"),
      dataIndex: "rbac_roles",
      align: "center",
      render: (names: string[]) => (
        <Space size={4} wrap>
          {(names || []).slice(0, 2).map((n) => (
            <span key={n} className={styles.toneViolet}>
              {roleDisplay(n)}
            </span>
          ))}
          {(names || []).length > 2 ? (
            <Tooltip title={names.map(roleDisplay).join("、")}>
              <span className={styles.toneGray}>+{names.length - 2}</span>
            </Tooltip>
          ) : null}
        </Space>
      ),
    },
    {
      title: t("admin.org.colDept", "部门"),
      dataIndex: "department_names",
      align: "center",
      ellipsis: true,
      render: (names: string[]) => (
        <Tooltip title={(names || []).join("、")}>
          <span>{(names || []).join("、") || "—"}</span>
        </Tooltip>
      ),
    },
    {
      title: t("common.actions", "操作"),
      key: "actions",
      align: "center",
      width: 120,
      render: (_: unknown, user) => (
        <HasPerm code="admin:usersUpdate">
          <Space size={4}>
            <Button
              type="link"
              size="small"
              onClick={() => openRenameMember(user)}
            >
              {t("common.edit", "编辑")}
            </Button>
          </Space>
        </HasPerm>
      ),
    },
  ];

  // 编辑成员档案（复用添加成员弹窗的编辑态）。
  const [editTarget, setEditTarget] = useState<AdminUserView | null>(null);
  function openRenameMember(user: AdminUserView) {
    setEditTarget(user);
    memberForm.setFieldsValue({
      username: user.username,
      real_name: user.real_name,
      phone: user.phone,
      gender: user.gender,
      position: user.position,
    });
    setMemberModal(true);
  }

  const submitMemberEdit = async () => {
    if (!editTarget) return;
    const values = await memberForm.validateFields();
    try {
      await adminUsersApi.update(editTarget.username, {
        real_name: values.real_name || "",
        phone: values.phone || "",
        gender: values.gender ?? 0,
        position: values.position || "",
        display_name: values.real_name || "",
      });
      message.success(t("admin.org.saved", "已保存"));
      setMemberModal(false);
      setEditTarget(null);
      loadUsers();
    } catch (err) {
      message.error(String(err));
    }
  };

  const closeMemberModal = () => {
    setMemberModal(false);
    setEditTarget(null);
  };

  const titleRender = (node: DataNode) => {
    const isRoot = node.key === "";
    const deptId = String(node.key);
    return (
      <div className={styles.treeNode}>
        <span className={styles.treeNodeTitle}>
          {isRoot ? <ApartmentOutlined style={{ marginRight: 6 }} /> : null}
          {String(node.title)}
        </span>
        {!isRoot && (
          <span className={styles.treeNodeActions}>
            <HasPerm code="admin:orgsCreate">
              <Tooltip title={t("admin.org.addChild", "新建子部门")}>
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    openCreateDept(deptId);
                  }}
                />
              </Tooltip>
            </HasPerm>
            <HasPerm code="admin:orgsUpdate">
              <Tooltip title={t("admin.org.rename", "重命名")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    openRenameDept(deptId, String(node.title));
                  }}
                />
              </Tooltip>
            </HasPerm>
            <HasPerm code="admin:orgsDelete">
              <Popconfirm
                title={t("admin.org.deleteConfirm", "删除该部门？（需为空）")}
                onConfirm={(e) => {
                  e?.stopPropagation();
                  deleteDept(deptId);
                }}
                onCancel={(e) => e?.stopPropagation()}
              >
                <Tooltip title={t("admin.org.delete", "删除")}>
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Tooltip>
              </Popconfirm>
            </HasPerm>
          </span>
        )}
      </div>
    );
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "管理")}
        current={t("nav.adminOrg", "部门员工")}
      />
      <div className={styles.workspaceLayout}>
        {/* 左栏：部门树 */}
        <div className={styles.sidePanel}>
          <Input
            allowClear
            placeholder={t("admin.org.searchDept", "请输入部门名称")}
            prefix={<SearchOutlined />}
            value={treeSearch}
            onChange={(e) => setTreeSearch(e.target.value)}
          />
          <div className={styles.sidePanelBody}>
            <Tree
              showLine
              defaultExpandAll
              treeData={treeData}
              titleRender={titleRender}
              selectedKeys={[selected ?? ""]}
              onSelect={(keys) =>
                setSelected(keys.length && keys[0] !== "" ? String(keys[0]) : null)
              }
            />
          </div>
          <HasPerm code="admin:orgsCreate">
            <Button
              type="dashed"
              block
              icon={<PlusOutlined />}
              onClick={() => openCreateDept(selected)}
            >
              {t("admin.org.create", "新建部门")}
            </Button>
          </HasPerm>
        </div>

        {/* 右栏：员工列表 */}
        <div className={styles.mainPanel}>
          <div>
            <div className={styles.breadcrumb}>{breadcrumb}</div>
            <h3 className={styles.mainTitle}>
              {t("admin.org.deptMembers", "部门人员")}
            </h3>
          </div>

          <div className={styles.filterBar}>
            <div className={styles.filterBarGroup}>
              <HasPerm code="admin:usersCreate">
                <Button
                  type="primary"
                  icon={<UserAddOutlined />}
                  onClick={openAddMember}
                >
                  {t("admin.org.addMember", "添加成员")}
                </Button>
              </HasPerm>
              <HasPerm code="admin:orgsAssignMember">
                <Button
                  icon={<SwapOutlined />}
                  disabled={!selectedRowKeys.length}
                  onClick={openMove}
                >
                  {t("admin.org.moveDept", "调整部门")}
                </Button>
              </HasPerm>
              <HasPerm code="admin:orgsAssignMember">
                <Popconfirm
                  title={t(
                    "admin.org.batchRemoveConfirm",
                    "将选中成员移出当前部门？",
                  )}
                  onConfirm={batchRemove}
                  disabled={!selectedRowKeys.length || !selected}
                >
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    disabled={!selectedRowKeys.length || !selected}
                  >
                    {t("admin.org.batchDelete", "批量删除")}
                  </Button>
                </Popconfirm>
              </HasPerm>
            </div>
            <div className={styles.filterBarGroup}>
              <Segmented
                value={status}
                onChange={(v) => setStatus(v as typeof status)}
                options={[
                  { label: t("admin.org.all", "全部"), value: "all" },
                  { label: t("admin.org.enabled", "启用"), value: "enabled" },
                  { label: t("admin.org.disabled", "禁用"), value: "disabled" },
                ]}
              />
              <Input
                style={{ width: 240 }}
                placeholder={t(
                  "admin.org.searchMember",
                  "姓名/手机号/登录账号",
                )}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={loadUsers}
                allowClear
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={loadUsers}>
                {t("common.query", "查询")}
              </Button>
              <Button icon={<ReloadOutlined />} onClick={resetFilters}>
                {t("common.reset", "重置")}
              </Button>
            </div>
          </div>

          <Table<AdminUserView>
            rowKey="username"
            loading={loading}
            dataSource={users}
            columns={columns}
            scroll={{ x: 1080 }}
            rowSelection={{
              selectedRowKeys,
              onChange: (keys) => setSelectedRowKeys(keys as string[]),
            }}
            locale={{
              emptyText: (
                <Empty
                  description={t(
                    "admin.org.noMembers",
                    "该部门暂无人员，点击「添加成员」创建",
                  )}
                />
              ),
            }}
            pagination={{
              pageSize: 10,
              showSizeChanger: true,
              total: users.length,
              showTotal: (n) =>
                t("admin.org.totalCount", { count: n, defaultValue: "共 {{count}} 条" }),
            }}
          />
        </div>
      </div>

      {/* 部门新建/重命名弹窗 */}
      <Modal
        title={
          deptModal.mode === "create"
            ? t("admin.org.create", "新建部门")
            : t("admin.org.rename", "重命名部门")
        }
        open={deptModal.open}
        onOk={submitDept}
        onCancel={() => setDeptModal({ open: false, mode: "create" })}
        destroyOnHidden
      >
        <Form form={deptForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.org.name", "部门名称")}
            rules={[{ required: true, message: t("admin.org.nameRequired", "请输入部门名称") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加/编辑成员弹窗 */}
      <Modal
        title={
          editTarget
            ? t("admin.org.editMember", "编辑成员")
            : t("admin.org.addMember", "添加成员")
        }
        open={memberModal}
        onOk={editTarget ? submitMemberEdit : submitMember}
        onCancel={closeMemberModal}
        destroyOnHidden
      >
        <Form form={memberForm} layout="vertical" preserve={false}>
          {!editTarget && (
            <Form.Item
              name="username"
              label={t("admin.org.colAccount", "登录账号")}
              rules={[{ required: true, message: t("admin.org.accountRequired", "请输入登录账号") }]}
            >
              <Input />
            </Form.Item>
          )}
          <Form.Item
            name="real_name"
            label={t("admin.org.colName", "姓名")}
            rules={
              editTarget ? [] : [{ required: true, message: t("admin.org.nameRequired2", "请输入姓名") }]
            }
          >
            <Input />
          </Form.Item>
          <Form.Item name="phone" label={t("admin.org.colPhone", "手机号")}>
            <Input />
          </Form.Item>
          <Form.Item name="gender" label={t("admin.org.colGender", "性别")} initialValue={0}>
            <Select
              options={[
                { value: 0, label: t("admin.org.genderUnknown", "未知") },
                { value: 1, label: t("admin.org.genderMale", "男") },
                { value: 2, label: t("admin.org.genderFemale", "女") },
              ]}
            />
          </Form.Item>
          <Form.Item name="position" label={t("admin.org.colPosition", "职位")}>
            <Input />
          </Form.Item>
          {!editTarget && (
            <>
              <Form.Item
                name="password"
                label={t("admin.org.initPassword", "初始密码")}
                rules={[{ required: true, message: t("admin.org.pwdRequired", "请输入初始密码") }]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Form.Item name="rbac_role" label={t("admin.org.colRoles", "角色")}>
                <Select
                  allowClear
                  placeholder={t("admin.org.pickRole", "选择角色")}
                  options={roles.map((r) => ({
                    value: r.name,
                    label: r.display_name || r.name,
                  }))}
                />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 调整部门弹窗 */}
      <Modal
        title={t("admin.org.moveDept", "调整部门")}
        open={moveModal}
        onOk={submitMove}
        onCancel={() => setMoveModal(false)}
        destroyOnHidden
      >
        <Form form={moveForm} layout="vertical" preserve={false}>
          <Form.Item
            name="target_dept_id"
            label={t("admin.org.targetDept", "目标部门")}
            rules={[{ required: true, message: t("admin.org.pickTargetDept", "请选择目标部门") }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t("admin.org.pickTargetDept", "请选择目标部门")}
              options={flattenDeptOptions(tree)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );

  function flattenDeptOptions(
    nodes: DepartmentTree[],
    prefix = "",
  ): { value: string; label: string }[] {
    return nodes.flatMap((node) => [
      { value: node.id, label: `${prefix}${node.name}` },
      ...flattenDeptOptions(node.children || [], `${prefix}${node.name} / `),
    ]);
  }
}

export default OrganizationPage;
