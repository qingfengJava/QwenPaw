/**
 * Admin/MenuManagement — 菜单管理（M7 PG-RBAC，企业级树形表格版）。
 *
 * 对齐 SmartAdmin 式后台：顶部筛选工具行（关键字/类型/显示状态 + 查询/重置），
 * 下方可展开的树形表格（名称/类型/图标/路由/组件/权限/排序/操作），
 * 支持新增（顶级/子级）、编辑、删除、批量删除、重置为默认。
 * 编辑通过 Modal 表单完成；保存成功后同步刷新侧栏菜单缓存。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { HasPerm } from "@/components/HasPerm";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminMenusApi, adminPermissionsApi } from "../../api/modules/admin";
import type {
  MenuCreateBody,
  MenuUpdateBody,
  PermissionRecord,
} from "../../api/modules/admin";
import { usePermissionStore, type MenuItem } from "../../stores/permissionStore";
import { ICON_NAMES, resolveMenuIcon } from "@/layouts/registry/iconRegistry";
import styles from "./admin.module.less";

const { Text } = Typography;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** 图标下拉选项：名字 + 预览图标（数据→组件统一走 iconRegistry）。 */
const ICON_OPTIONS = ICON_NAMES.map((name) => {
  const IconComp = resolveMenuIcon(name);
  return {
    value: name,
    label: (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <IconComp size={16} />
        {name}
      </span>
    ),
  };
});

/** 渲染菜单图标名对应的组件；无图标时返回 null。 */
function renderMenuIcon(name: string) {
  if (!name) return null;
  const IconComp = resolveMenuIcon(name);
  return <IconComp size={16} />;
}

/** 收集树中所有节点 id（用于展开/折叠全部）。 */
function collectAllIds(items: MenuItem[], acc: string[] = []): string[] {
  for (const item of items) {
    acc.push(item.id);
    if (item.children?.length) collectAllIds(item.children, acc);
  }
  return acc;
}

/** 扁平化树为 id → 节点 映射。 */
function flattenMenus(
  items: MenuItem[],
  map = new Map<string, MenuItem>(),
): Map<string, MenuItem> {
  for (const item of items) {
    map.set(item.id, item);
    if (item.children?.length) flattenMenus(item.children, map);
  }
  return map;
}

/** 上级菜单选项（编辑时排除自身及其子树，防止环）。 */
function buildParentOptions(
  items: MenuItem[],
  excludeId?: string,
): { value: string; label: string }[] {
  const opts: { value: string; label: string }[] = [
    { value: "", label: "— 顶级菜单 —" },
  ];
  const walk = (nodes: MenuItem[], prefix = "") => {
    for (const node of nodes) {
      if (node.id === excludeId) continue; // 跳过自身及其子树
      if (node.menu_type !== "button") {
        opts.push({ value: node.id, label: `${prefix}${node.name}` });
      }
      if (node.children?.length) walk(node.children, `${prefix}${node.name} / `);
    }
  };
  walk(items);
  return opts;
}

/** 筛选条件（点击查询后生效）。 */
interface MenuFilter {
  keyword: string;
  menuType: string | undefined;
  visible: string | undefined;
}

const EMPTY_FILTER: MenuFilter = { keyword: "", menuType: undefined, visible: undefined };

/** 单节点是否命中筛选。 */
function matchesFilter(item: MenuItem, f: MenuFilter): boolean {
  if (f.menuType && item.menu_type !== f.menuType) return false;
  if (f.visible === "yes" && !item.is_visible) return false;
  if (f.visible === "no" && item.is_visible) return false;
  if (f.keyword) {
    const needle = f.keyword.trim().toLowerCase();
    const hay = `${item.name} ${item.path} ${item.component} ${item.perm_code}`.toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  return true;
}

/**
 * 按筛选条件裁剪菜单树：命中节点保留完整子树；未命中但有命中后代的
 * 祖先节点保留（仅挂命中分支），保证层级上下文可见。
 */
function filterTree(items: MenuItem[], f: MenuFilter): MenuItem[] {
  const result: MenuItem[] = [];
  for (const item of items) {
    if (matchesFilter(item, f)) {
      result.push(item);
      continue;
    }
    if (item.children?.length) {
      const kept = filterTree(item.children, f);
      if (kept.length) result.push({ ...item, children: kept });
    }
  }
  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function MenuManagementPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [tree, setTree] = useState<MenuItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [permissions, setPermissions] = useState<PermissionRecord[]>([]);

  // 筛选：输入中的条件与已应用条件分离（点「查询」才生效，对齐企业后台习惯）
  const [draftFilter, setDraftFilter] = useState<MenuFilter>(EMPTY_FILTER);
  const [appliedFilter, setAppliedFilter] = useState<MenuFilter>(EMPTY_FILTER);

  // 展开/折叠
  const [expandedIds, setExpandedIds] = useState<string[]>([]);

  // 选择与编辑弹窗
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const filterActive =
    !!appliedFilter.keyword || !!appliedFilter.menuType || !!appliedFilter.visible;

  // ── Data loading ──────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [treeData, permList] = await Promise.all([
        adminMenusApi.getTree(),
        adminPermissionsApi.list().catch(() => [] as PermissionRecord[]),
      ]);
      setTree(treeData);
      setPermissions(permList);
      setExpandedIds(collectAllIds(treeData));
      // 同步刷新导航菜单缓存，使侧栏无需整页刷新即反映菜单变更。
      void usePermissionStore
        .getState()
        .fetchMenus()
        .catch(() => undefined);
    } catch (err) {
      console.error("Failed to load menus:", err);
      message.error(t("admin.menus.loadFailed", "Failed to load menus"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  // 强制重置菜单为内置 seed 结构（覆盖当前编辑）。
  const handleReseed = async () => {
    try {
      await adminMenusApi.reseed();
      message.success(t("admin.menus.reseeded", "菜单已重置为默认"));
      setSelectedIds([]);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  // ── Derived data ──────────────────────────────────────────────────────────

  const displayTree = useMemo(
    () => (filterActive ? filterTree(tree, appliedFilter) : tree),
    [tree, appliedFilter, filterActive],
  );

  const menuMap = useMemo(() => flattenMenus(tree), [tree]);

  const parentOptions = useMemo(
    () => buildParentOptions(tree, editingId ?? undefined),
    [tree, editingId],
  );

  const menuTypeOptions = [
    { value: "directory", label: t("admin.menus.typeDirectory", "目录") },
    { value: "menu", label: t("admin.menus.typeMenu", "菜单") },
    { value: "button", label: t("admin.menus.typeButton", "按钮") },
  ];

  const permOptions = permissions.map((p) => ({
    value: p.code,
    label: `${p.code} — ${p.name}`,
  }));

  // ── Handlers ──────────────────────────────────────────────────────────────

  const doSearch = () => setAppliedFilter({ ...draftFilter });

  const doReset = () => {
    setDraftFilter(EMPTY_FILTER);
    setAppliedFilter(EMPTY_FILTER);
  };

  const toggleExpandAll = () => {
    setExpandedIds((prev) =>
      prev.length ? [] : collectAllIds(displayTree),
    );
  };

  const openCreateModal = (parentId?: string | null, presetType?: MenuItem["menu_type"]) => {
    setEditingId(null);
    form.setFieldsValue({
      parent_id: parentId ?? "",
      name: "",
      menu_type: presetType ?? "menu",
      path: "",
      component: "",
      icon: "",
      perm_code: "",
      sort_order: 0,
      is_visible: true,
      is_enabled: true,
      is_external: false,
      redirect: "",
    });
    setModalOpen(true);
  };

  const openEditModal = (menu: MenuItem) => {
    setEditingId(menu.id);
    form.setFieldsValue({
      parent_id: menu.parent_id ?? "",
      name: menu.name,
      menu_type: menu.menu_type,
      path: menu.path,
      component: menu.component,
      icon: menu.icon,
      perm_code: menu.perm_code,
      sort_order: menu.sort_order,
      is_visible: menu.is_visible,
      is_enabled: menu.is_enabled,
      is_external: menu.is_external,
      redirect: menu.redirect,
    });
    setModalOpen(true);
  };

  const handleModalOk = async () => {
    const values = await form.validateFields();
    const payload = {
      parent_id: values.parent_id || null,
      name: values.name,
      menu_type: values.menu_type,
      path: values.path ?? "",
      component: values.component ?? "",
      icon: values.icon ?? "",
      perm_code: values.perm_code ?? "",
      sort_order: values.sort_order ?? 0,
      is_visible: values.is_visible ?? true,
      is_enabled: values.is_enabled ?? true,
      is_external: values.is_external ?? false,
      redirect: values.redirect ?? "",
    };
    setSaving(true);
    try {
      if (editingId) {
        await adminMenusApi.update(editingId, payload as MenuUpdateBody);
        message.success(t("admin.menus.saved", "Menu saved"));
      } else {
        await adminMenusApi.create(payload as MenuCreateBody);
        message.success(t("admin.menus.created", "Menu created"));
      }
      setModalOpen(false);
      load();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await adminMenusApi.delete(id);
      message.success(t("admin.menus.deleted", "Menu deleted"));
      setSelectedIds((prev) => prev.filter((x) => x !== id));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  /** 批量删除：剔除祖先同样被选中的子项（父级联删已覆盖），逐条调用删除接口。 */
  const handleBatchDelete = async () => {
    const idSet = new Set(selectedIds);
    const hasSelectedAncestor = (item: MenuItem): boolean => {
      let p = item.parent_id;
      while (p) {
        if (idSet.has(p)) return true;
        p = menuMap.get(p)?.parent_id ?? null;
      }
      return false;
    };
    const targets = selectedIds.filter((id) => {
      const m = menuMap.get(id);
      return m ? !hasSelectedAncestor(m) : true;
    });
    try {
      for (const id of targets) {
        await adminMenusApi.delete(id);
      }
      message.success(
        t("admin.menus.batchDeleted", "已删除 {{count}} 个菜单", {
          count: targets.length,
        }),
      );
      setSelectedIds([]);
      load();
    } catch (err) {
      message.error(String(err));
      load();
    }
  };

  // ── Table columns ─────────────────────────────────────────────────────────

  const watchType = Form.useWatch("menu_type", form);
  const watchExternal = Form.useWatch("is_external", form);

  /** 类型 → tone 标签（目录蓝 / 菜单橙 / 按钮绿，对齐企业后台配色）。 */
  const typeTag = (type: MenuItem["menu_type"]) => {
    if (type === "directory") {
      return (
        <span className={styles.toneBlue}>{t("admin.menus.typeDirectory", "目录")}</span>
      );
    }
    if (type === "menu") {
      return (
        <span className={styles.toneAmber}>
          {t("admin.menus.typeMenu", "菜单")}
        </span>
      );
    }
    return <span className={styles.toneGreen}>{t("admin.menus.typeButton", "按钮")}</span>;
  };

  const columns: ColumnsType<MenuItem> = [
    {
      title: t("admin.menus.name", "菜单名称"),
      dataIndex: "name",
      key: "name",
      align: "center",
      width: 240,
      render: (_: string, record) => (
        <Space size={6}>
          {record.icon ? (
            <span style={{ display: "inline-flex", color: "var(--pg-ink-2, #4c5670)" }}>
              {renderMenuIcon(record.icon)}
            </span>
          ) : null}
          <Text strong={record.menu_type !== "button"}>{record.name}</Text>
        </Space>
      ),
    },
    {
      title: t("admin.menus.menuType", "类型"),
      dataIndex: "menu_type",
      key: "menu_type",
      align: "center",
      width: 90,
      render: (_: unknown, record) => typeTag(record.menu_type),
    },
    {
      title: t("admin.menus.icon", "图标"),
      dataIndex: "icon",
      key: "icon",
      align: "center",
      width: 80,
      render: (icon: string) =>
        icon ? (
          <Tooltip title={icon}>
            <span style={{ display: "inline-flex", color: "var(--pg-ink, #101623)" }}>
              {renderMenuIcon(icon)}
            </span>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("admin.menus.path", "路由"),
      dataIndex: "path",
      key: "path",
      align: "center",
      width: 190,
      ellipsis: { showTitle: false },
      render: (path: string) =>
        path ? (
          <Tooltip title={path}>
            <Text code>{path}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("admin.menus.component", "组件"),
      dataIndex: "component",
      key: "component",
      align: "center",
      width: 210,
      ellipsis: { showTitle: false },
      render: (component: string) =>
        component ? (
          <Tooltip title={component}>
            <Text code>{component}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("admin.menus.permCode", "权限标识"),
      dataIndex: "perm_code",
      key: "perm_code",
      align: "center",
      width: 190,
      ellipsis: { showTitle: false },
      render: (code: string) =>
        code ? (
          <Tooltip title={code}>
            <Tag bordered={false} style={{ maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis" }}>
              {code}
            </Tag>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("admin.menus.sortOrder", "排序"),
      dataIndex: "sort_order",
      key: "sort_order",
      align: "center",
      width: 70,
    },
    {
      title: t("admin.menus.visibleCol", "显示"),
      dataIndex: "is_visible",
      key: "is_visible",
      align: "center",
      width: 80,
      render: (visible: boolean) =>
        visible ? (
          <span className={styles.toneGreen}>{t("admin.menus.showYes", "显示")}</span>
        ) : (
          <span className={styles.toneGray}>{t("admin.menus.showNo", "隐藏")}</span>
        ),
    },
    {
      title: t("admin.menus.action", "操作"),
      key: "action",
      align: "center",
      width: 210,
      fixed: "right",
      render: (_: unknown, record) => (
        <Space size={4}>
          <HasPerm code="admin:menusCreate">
            {record.menu_type !== "button" && (
              <Button
                type="link"
                size="small"
                onClick={() =>
                  openCreateModal(
                    record.id,
                    record.menu_type === "directory" ? "menu" : "button",
                  )
                }
              >
                {t("admin.menus.createChild", "新增子菜单")}
              </Button>
            )}
          </HasPerm>
          <HasPerm code="admin:menusUpdate">
            <Button type="link" size="small" onClick={() => openEditModal(record)}>
              {t("common.edit", "编辑")}
            </Button>
          </HasPerm>
          <HasPerm code="admin:menusDelete">
            <Popconfirm
              title={t(
                "admin.menus.deleteConfirm",
                "确定删除此菜单项？子菜单也将被删除。",
              )}
              onConfirm={() => handleDelete(record.id)}
            >
              <Button type="link" size="small" danger>
                {t("common.delete", "删除")}
              </Button>
            </Popconfirm>
          </HasPerm>
        </Space>
      ),
    },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminMenus", "Menu Management")}
        extra={
          <HasPerm code="admin:menus">
            <Space>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => openCreateModal(null)}
              >
                {t("admin.menus.createRoot", "新增顶级菜单")}
              </Button>
              <Popconfirm
                title={t(
                  "admin.menus.reseedConfirm",
                  "确定重置为默认菜单？当前所有菜单编辑将被覆盖。",
                )}
                onConfirm={handleReseed}
              >
                <Button danger icon={<ReloadOutlined />}>
                  {t("admin.menus.reseed", "重置为默认")}
                </Button>
              </Popconfirm>
            </Space>
          </HasPerm>
        }
      />

      {/* 筛选工具行 */}
      <div className={styles.panel} style={{ marginBottom: 14 }}>
        <div className={styles.filterBar}>
          <div className={styles.filterBarGroup}>
            <span className={styles.breadcrumb}>
              {t("admin.menus.keyword", "关键字：")}
            </span>
            <Input
              allowClear
              style={{ width: 260 }}
              value={draftFilter.keyword}
              onChange={(e) =>
                setDraftFilter((f) => ({ ...f, keyword: e.target.value }))
              }
              onPressEnter={doSearch}
              placeholder={t(
                "admin.menus.keywordPlaceholder",
                "菜单名称/路由地址/组件路径/权限字符串",
              )}
            />
            <span className={styles.breadcrumb}>
              {t("admin.menus.filterType", "类型：")}
            </span>
            <Select
              allowClear
              style={{ width: 130 }}
              value={draftFilter.menuType}
              onChange={(v) => setDraftFilter((f) => ({ ...f, menuType: v }))}
              placeholder={t("admin.menus.pleaseSelect", "请选择")}
              options={menuTypeOptions}
            />
            <span className={styles.breadcrumb}>
              {t("admin.menus.filterVisible", "显示：")}
            </span>
            <Select
              allowClear
              style={{ width: 130 }}
              value={draftFilter.visible}
              onChange={(v) => setDraftFilter((f) => ({ ...f, visible: v }))}
              placeholder={t("admin.menus.pleaseSelect", "请选择")}
              options={[
                { value: "yes", label: t("admin.menus.showYes", "显示") },
                { value: "no", label: t("admin.menus.showNo", "隐藏") },
              ]}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={doSearch}>
              {t("admin.menus.search", "查询")}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={doReset}>
              {t("common.reset", "重置")}
            </Button>
          </div>
        </div>
      </div>

      {/* 树形表格 */}
      <div className={styles.panel}>
        <div className={styles.filterBar} style={{ marginBottom: 12 }}>
          <div className={styles.filterBarGroup}>
            <HasPerm code="admin:menusCreate">
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => openCreateModal(null)}
              >
                {t("admin.menus.addMenu", "添加菜单")}
              </Button>
            </HasPerm>
            <HasPerm code="admin:menusDelete">
              <Popconfirm
                title={t(
                  "admin.menus.batchDeleteConfirm",
                  "确定批量删除选中的 {{count}} 个菜单？子菜单也将被删除。",
                  { count: selectedIds.length },
                )}
                onConfirm={handleBatchDelete}
                disabled={!selectedIds.length}
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!selectedIds.length}
                >
                  {t("admin.menus.batchDelete", "批量删除")}
                </Button>
              </Popconfirm>
            </HasPerm>
          </div>
          <div className={styles.filterBarGroup}>
            <Button type="text" onClick={toggleExpandAll}>
              {expandedIds.length
                ? t("admin.menus.collapseAll", "折叠全部")
                : t("admin.menus.expandAll", "展开全部")}
            </Button>
          </div>
        </div>
        <Table<MenuItem>
          rowKey="id"
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={displayTree}
          pagination={false}
          scroll={{ x: 1250 }}
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: (keys) => setSelectedIds(keys.map(String)),
          }}
          expandable={{
            expandedRowKeys: expandedIds,
            onExpandedRowsChange: (keys) =>
              setExpandedIds(Array.from(keys).map(String)),
          }}
        />
      </div>

      {/* 新增/编辑弹窗 */}
      <Modal
        title={
          editingId
            ? t("admin.menus.editTitle", "编辑菜单")
            : t("admin.menus.createTitle", "新增菜单")
        }
        open={modalOpen}
        onOk={handleModalOk}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        width={600}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="parent_id" label={t("admin.menus.parent", "上级菜单")}>
            <Select options={parentOptions} allowClear showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("admin.menus.name", "菜单名称")}
            rules={[
              {
                required: true,
                message: t("admin.menus.nameRequired", "请输入菜单名称"),
              },
            ]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="menu_type"
            label={t("admin.menus.menuType", "菜单类型")}
            rules={[{ required: true }]}
          >
            <Radio.Group options={menuTypeOptions} optionType="button" />
          </Form.Item>
          {watchType !== "button" && (
            <Form.Item name="icon" label={t("admin.menus.icon", "图标")}>
              <Select
                options={ICON_OPTIONS}
                showSearch
                allowClear
                optionFilterProp="value"
                placeholder={t("admin.menus.iconPlaceholder", "选择图标")}
              />
            </Form.Item>
          )}
          {watchType !== "button" && (
            <Form.Item name="path" label={t("admin.menus.path", "路由路径")}>
              <Input placeholder="/admin/menus" />
            </Form.Item>
          )}
          {watchType === "menu" && (
            <Form.Item
              name="component"
              label={t("admin.menus.component", "组件路径")}
              tooltip={t(
                "admin.menus.componentHint",
                "相对 pages 的路径，如 Admin/MenuManagement",
              )}
            >
              <Input placeholder="Admin/MenuManagement" />
            </Form.Item>
          )}
          <Form.Item
            name="perm_code"
            label={t("admin.menus.permCode", "权限标识")}
            tooltip={t(
              "admin.menus.permCodeHint",
              "按钮型菜单必须绑定权限码；目录/菜单可选",
            )}
            rules={
              watchType === "button"
                ? [
                    {
                      required: true,
                      message: t(
                        "admin.menus.permCodeRequired",
                        "按钮必须选择权限标识",
                      ),
                    },
                  ]
                : undefined
            }
          >
            <Select
              options={permOptions}
              allowClear
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
              }
              placeholder={t("admin.menus.permCodePlaceholder", "选择权限码")}
            />
          </Form.Item>
          <Form.Item name="sort_order" label={t("admin.menus.sortOrder", "排序")}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
          <Space size="large" style={{ marginBottom: 16 }}>
            <Form.Item
              name="is_visible"
              label={t("admin.menus.isVisible", "是否可见")}
              valuePropName="checked"
              style={{ marginBottom: 0 }}
            >
              <Radio.Group
                options={[
                  { value: true, label: t("common.yes", "是") },
                  { value: false, label: t("common.no", "否") },
                ]}
                optionType="button"
              />
            </Form.Item>
            <Form.Item
              name="is_enabled"
              label={t("admin.menus.isEnabled", "是否启用")}
              valuePropName="checked"
              style={{ marginBottom: 0 }}
            >
              <Radio.Group
                options={[
                  { value: true, label: t("common.yes", "是") },
                  { value: false, label: t("common.no", "否") },
                ]}
                optionType="button"
              />
            </Form.Item>
            <Form.Item
              name="is_external"
              label={t("admin.menus.isExternal", "是否外链")}
              valuePropName="checked"
              style={{ marginBottom: 0 }}
            >
              <Radio.Group
                options={[
                  { value: true, label: t("common.yes", "是") },
                  { value: false, label: t("common.no", "否") },
                ]}
                optionType="button"
              />
            </Form.Item>
          </Space>
          {watchExternal && (
            <Form.Item name="redirect" label={t("admin.menus.redirect", "重定向地址")}>
              <Input placeholder="https://example.com" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}

export default MenuManagementPage;
