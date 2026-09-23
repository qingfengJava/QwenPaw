/**
 * Agents/AgentsConsolePage.tsx — 数字员工控制台（企业级分类与部门治理）。
 *
 * 取代原「全部 agent 平铺一张表」的列表页，解决两个平台级问题：
 *
 * 1. **形态分类**：智能体（原生 + 数字员工）/ 专家团 / 工作流 三类分 Tab，
 *    卡片形态按类别差异化（团卡显示成员堆叠与编排模式），工作流为外部平台
 *    对接预留（骨架在位、无数据不造假）；
 * 2. **部门治理**：归属部门 + 可见范围（全员共享 / 部门专属 / 仅创建者）在
 *    本页直接管理，卡片视图看资产、表格视图批量治理。
 *
 * 数据全部来自 `GET /agents/registry`（单一来源），本页不再拼任何枚举文案。
 * 卡片主体与箭头一律新标签页打开工作台（草稿员工无工作台，转能力配置页）。
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Button,
  Dropdown,
  Input,
  Segmented,
  Select,
  Space,
  Switch,
  Tooltip,
  TreeSelect,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  Building2,
  LayoutGrid,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Table2,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatCard, UnderlineTabs } from "@/components/staffdeck";
import { useAppMessage } from "@/hooks/useAppMessage";
import { useAuthStore, selectIsAdmin } from "@/stores/authStore";
import { useAgents } from "@/pages/Settings/Agents/useAgents";
import { agentsApi } from "@/api/modules/agents";
import { AgentModal, CopyAgentModal } from "@/pages/Settings/Agents/components";
import type { AgentSummary } from "@/api/types/agents";
import { openAgentWorkbench } from "@/utils/openAgentWorkbench";
import {
  useEmployeeRegistry,
  type EmployeeTabKey,
} from "@/hooks/useEmployeeRegistry";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import { EmployeeKindCard } from "./console/EmployeeKindCard";
import { TeamKindCard } from "./console/TeamKindCard";
import { GovernanceTable } from "./console/GovernanceTable";
import { GovernanceModal } from "./console/GovernanceModal";
import { WorkflowEmptyState } from "./console/WorkflowEmptyState";
import { useAgentFormModal } from "./console/useAgentFormModal";
import { computeReorder } from "./console/reorder";
import styles from "./console/console.module.less";

/** 生命周期筛选项（只有专家/团有生命周期，原生智能体不参与）。 */
const LIFECYCLE_OPTIONS = ["draft", "published", "archived"];

/** 可见范围筛选项（与后端 VISIBILITIES 常量一致）。 */
const VISIBILITY_OPTIONS = ["org", "department", "private"];

/** 深链可携带的 Tab（工作台「查看全部」按形态直达）。 */
const TAB_KEYS: EmployeeTabKey[] = ["all", "agents", "team", "workflow"];

export default function AgentsConsolePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { message } = useAppMessage();
  const isAdmin = useAuthStore(selectIsAdmin);
  const { deleteAgent, toggleAgent, pinAgent, loadAgents } = useAgents();
  const {
    rows,
    filtered,
    groupedByDepartment,
    departments,
    stats,
    loading,
    error,
    filters,
    setFilter,
    resetFilters,
    reload,
    saveGovernance,
    saveBatchGovernance,
  } = useEmployeeRegistry();

  const [view, setView] = useState<"grid" | "table">("grid");
  const [grouped, setGrouped] = useState(false);
  const [governTargets, setGovernTargets] = useState<DigitalEmployee[]>([]);
  const [governOpen, setGovernOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // 深链 `?tab=agents|team|workflow` 直达分类（浏览器前进/后退同样生效）
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const tab = searchParams.get("tab") as EmployeeTabKey | null;
    if (tab && TAB_KEYS.includes(tab)) setFilter("tab", tab);
  }, [searchParams, setFilter]);

  const modals = useAgentFormModal({
    onUpdated: async () => {
      await Promise.all([reload(), loadAgents()]);
    },
    onCreated: (agentId) => openAgentWorkbench(agentId),
    onCopied: () => reload(),
  });

  const departmentTreeData = useMemo(
    () =>
      departments.map((node) => ({
        value: node.id,
        title: node.name,
        children: node.children.length
          ? node.children.map((child) => ({
              value: child.id,
              title: child.name,
            }))
          : undefined,
      })),
    [departments],
  );

  const selectedRows = useMemo(
    () => filtered.filter((row) => selectedIds.includes(row.agent_id)),
    [filtered, selectedIds],
  );

  const openEmployee = (employee: DigitalEmployee) => {
    if (employee.usable) {
      openAgentWorkbench(employee.agent_id);
      return;
    }
    // 草稿员工没有运行时工作台，唯一入口是能力配置页
    if (employee.entity_kind === "expert" && isAdmin) {
      navigate(`/agents/manage/${encodeURIComponent(employee.entity_id)}`);
      return;
    }
    message.info(t("employee.hint.notPublished"));
  };

  const openCapabilities = (employee: DigitalEmployee) => {
    if (employee.entity_kind === "team") {
      navigate("/agents/teams");
      return;
    }
    navigate(`/agents/manage/${encodeURIComponent(employee.entity_id)}`);
  };

  /** 把注册表行还原成 AgentSummary 供既有编辑/复制弹窗使用。 */
  const toAgentSummary = (employee: DigitalEmployee): AgentSummary => ({
    id: employee.agent_id,
    name: employee.name,
    description: employee.description,
    workspace_dir: employee.workspace_dir,
    enabled: employee.enabled,
    pinned: employee.pinned,
    startup_status: (employee.startup_status || "pending") as AgentSummary["startup_status"],
    backend: employee.backend,
    backend_capabilities: employee.backend_capabilities,
    backend_model: employee.model_label || null,
    active_model: null,
    managed_by_app: employee.managed_by_app,
    available_in_chat: employee.available_in_chat,
  });

  const handleToggle = async (employee: DigitalEmployee) => {
    try {
      await toggleAgent(employee.agent_id, !employee.enabled);
      await reload();
    } catch {
      // useAgents 内部已提示失败原因
    }
  };

  const handlePin = async (employee: DigitalEmployee) => {
    try {
      await pinAgent(employee.agent_id, !employee.pinned);
      await reload();
    } catch {
      // 同上
    }
  };

  const handleDelete = async (employee: DigitalEmployee) => {
    try {
      await deleteAgent(employee.agent_id);
      await reload();
    } catch {
      // 同上
    }
  };

  /**
   * 上移 / 下移：保留旧表格拖拽的排序能力（两键完成换位）。
   *
   * 后端要求提交与 configured profiles 全量相等的 id 清单，因此换位
   * 以全量列表为基准（筛选视图只用来定位移动目标的邻居），草稿员工
   * 无 profile 不参与；换位若破坏 default/置顶分组约束则本地拦截。
   */
  const handleMove = async (employee: DigitalEmployee, offset: -1 | 1) => {
    const result = computeReorder(rows, filtered, employee, offset);
    if (!result.ok) {
      return;
    }
    if (result.violatesGrouping) {
      message.warning(t("employee.reorderPinnedConstraint"));
      return;
    }
    try {
      await agentsApi.reorderAgents(result.ids);
      await Promise.all([reload(), loadAgents()]);
    } catch (err: unknown) {
      message.error(
        err instanceof Error ? err.message : t("employee.reorderFailed"),
      );
    }
  };

  const submitGovernance = async (payload: {
    department_id?: string | null;
    visibility?: "org" | "department" | "private";
    granted_departments?: string[];
  }) => {
    try {
      if (governTargets.length > 1) {
        await saveBatchGovernance(
          governTargets.map((row) => row.agent_id),
          payload,
        );
        setSelectedIds([]);
      } else if (governTargets.length === 1) {
        await saveGovernance(governTargets[0].agent_id, payload);
      }
      setGovernOpen(false);
      message.success(t("employee.governance.saved"));
    } catch (err: unknown) {
      message.error(
        err instanceof Error ? err.message : t("employee.governance.failed"),
      );
    }
  };

  const cardActions = (employee: DigitalEmployee) => (
    <Space size={2} onClick={(event) => event.stopPropagation()}>
      {isAdmin ? (
        <Tooltip title={t("employee.action.governance")}>
          <Button
            type="text"
            size="small"
            aria-label={t("employee.action.governance")}
            onClick={() => {
              setGovernTargets([employee]);
              setGovernOpen(true);
            }}
          >
            <ShieldCheck size={15} />
          </Button>
        </Tooltip>
      ) : null}
      <Dropdown
        trigger={["click"]}
        menu={{
          items: cardMenuItems(employee),
          onClick: ({ key }) => runCardMenu(key, employee),
        }}
      >
        <Button type="text" size="small" aria-label={t("common.actions")}>
          <MoreHorizontal size={15} />
        </Button>
      </Dropdown>
    </Space>
  );

  const cardMenuItems = (employee: DigitalEmployee) => {
    const items: { key: string; label: string; danger?: boolean }[] = [
      { key: "capabilities", label: t("employee.action.capabilities") },
      { key: "edit", label: t("employee.action.editBasic") },
      { key: "copy", label: t("common.copy") },
      { key: "moveUp", label: t("employee.action.moveUp") },
      { key: "moveDown", label: t("employee.action.moveDown") },
      employee.pinned
        ? { key: "unpin", label: t("employee.action.unpin") }
        : { key: "pin", label: t("employee.action.pin") },
      employee.enabled
        ? { key: "disable", label: t("common.disable") }
        : { key: "enable", label: t("common.enable") },
    ];
    // 删除只对原生智能体开放：专家/团的下架属生命周期操作，在能力配置页完成
    if (employee.entity_kind === "agent") {
      items.push({ key: "delete", label: t("common.delete"), danger: true });
    }
    return items;
  };

  const runCardMenu = (key: string, employee: DigitalEmployee) => {
    if (key === "capabilities") openCapabilities(employee);
    else if (key === "edit") void modals.openEdit(toAgentSummary(employee));
    else if (key === "copy") modals.openCopy(toAgentSummary(employee));
    else if (key === "moveUp") void handleMove(employee, -1);
    else if (key === "moveDown") void handleMove(employee, 1);
    else if (key === "pin" || key === "unpin") void handlePin(employee);
    else if (key === "enable" || key === "disable") void handleToggle(employee);
    else if (key === "delete") void handleDelete(employee);
  };

  const renderCard = (employee: DigitalEmployee) => (
    <div key={employee.agent_id}>
      {employee.entity_kind === "team" ? (
        <TeamKindCard
          employee={employee}
          onOpen={openEmployee}
          actions={cardActions(employee)}
        />
      ) : (
        <EmployeeKindCard
          employee={employee}
          onOpen={openEmployee}
          actions={cardActions(employee)}
        />
      )}
    </div>
  );

  const filterActive =
    Boolean(filters.departmentId) ||
    filters.unassignedOnly ||
    Boolean(filters.visibility) ||
    Boolean(filters.lifecycle) ||
    Boolean(filters.keyword) ||
    filters.agentKind !== "all";

  return (
    <div className={styles.console}>
      <PageHeader
        current={t("nav.employees")}
        extra={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {isAdmin ? (
              <Button
                icon={<Building2 size={15} />}
                onClick={() => navigate("/admin/organization")}
              >
                {t("employee.action.organization")}
              </Button>
            ) : null}
            <Dropdown
              trigger={["click"]}
              menu={{
                items: [
                  { key: "agent", label: t("employee.createOf.agent") },
                  ...(isAdmin
                    ? [{ key: "expert", label: t("employee.createOf.expert") }]
                    : []),
                  ...(isAdmin
                    ? [{ key: "team", label: t("employee.createOf.team") }]
                    : []),
                ],
                onClick: ({ key }) => {
                  if (key === "agent") modals.openCreate();
                  else if (key === "expert") navigate("/agents/manage");
                  else navigate("/agents/teams");
                },
              }}
            >
              <Button type="primary" icon={<Plus size={15} />}>
                {t("employee.create")}
              </Button>
            </Dropdown>
          </div>
        }
      />

      {/* 指标卡行：点击即快筛（数据全部来自本页注册表） */}
      <div className={styles.metrics}>
        <StatCard
          value={stats.total}
          label={t("employee.metric.total")}
          onClick={() => setFilter("tab", "all")}
        />
        <StatCard
          value={stats.running}
          label={t("employee.metric.running")}
          tone="green"
        />
        <StatCard
          value={stats.teams}
          label={t("employee.metric.teams")}
          onClick={() => setFilter("tab", "team")}
        />
        <StatCard
          value={stats.unassigned}
          label={t("employee.metric.unassigned")}
          sublabel={t("employee.metric.unassignedHint")}
          onClick={() => {
            // 待归属是治理工作清单：切表格视图便于逐行设归属，再点取消
            setView("table");
            setFilter("unassignedOnly", !filters.unassignedOnly);
          }}
        />
      </div>

      <div className={`pg-surface ${styles.tabCard}`}>
        <UnderlineTabs
          value={filters.tab}
          onChange={(key) => setFilter("tab", key as EmployeeTabKey)}
          items={[
            { key: "all", label: t("employee.tab.all"), count: stats.total },
            { key: "agents", label: t("employee.tab.agents"), count: stats.agents },
            { key: "team", label: t("employee.tab.teams"), count: stats.teams },
            { key: "workflow", label: t("employee.tab.workflow"), count: 0 },
          ]}
        />

        <div className={styles.toolbar}>
          {filters.tab === "agents" ? (
            <div className={styles.subFilter}>
              <SlidersHorizontal size={14} className={styles.subLabel} />
              <Segmented
                size="small"
                value={filters.agentKind}
                onChange={(value) =>
                  setFilter("agentKind", value as typeof filters.agentKind)
                }
                options={[
                  { value: "all", label: t("employee.agentSub.all") },
                  { value: "expert", label: t("employee.kind.expert") },
                  { value: "agent", label: t("employee.agentSub.native") },
                ]}
              />
            </div>
          ) : null}

          <TreeSelect
            style={{ minWidth: 168 }}
            size="small"
            treeData={departmentTreeData}
            value={filters.departmentId || undefined}
            allowClear
            treeDefaultExpandAll
            placeholder={t("employee.filter.department")}
            onChange={(value) => setFilter("departmentId", value ?? "")}
          />
          <Select
            size="small"
            style={{ minWidth: 132 }}
            value={filters.visibility || undefined}
            allowClear
            placeholder={t("employee.filter.visibility")}
            onChange={(value) => setFilter("visibility", value ?? "")}
            options={VISIBILITY_OPTIONS.map((value) => ({
              value,
              label: t(`employee.visibility.${value}`),
            }))}
          />
          <Select
            size="small"
            style={{ minWidth: 128 }}
            value={filters.lifecycle || undefined}
            allowClear
            placeholder={t("employee.filter.lifecycle")}
            onChange={(value) => setFilter("lifecycle", value ?? "")}
            options={LIFECYCLE_OPTIONS.map((value) => ({
              value,
              label: t(`employee.lifecycle.${value}`),
            }))}
          />
          <Input
            size="small"
            style={{ width: 200 }}
            allowClear
            prefix={<Search size={13} />}
            placeholder={t("employee.filter.search")}
            value={filters.keyword}
            onChange={(event) => setFilter("keyword", event.target.value)}
          />

          <span className={styles.toolbarSpacer} />

          {filterActive ? (
            <Button
              size="small"
              type="text"
              icon={<RotateCcw size={13} />}
              onClick={resetFilters}
            >
              {t("employee.filter.reset")}
            </Button>
          ) : null}

          {view === "grid" ? (
            <Space size={6}>
              <span className={styles.subLabel}>
                {t("employee.filter.groupByDepartment")}
              </span>
              <Switch size="small" checked={grouped} onChange={setGrouped} />
            </Space>
          ) : null}

          <Segmented
            size="small"
            value={view}
            onChange={(value) => setView(value as "grid" | "table")}
            options={[
              { value: "grid", icon: <LayoutGrid size={14} />, title: t("employee.view.grid") },
              { value: "table", icon: <Table2 size={14} />, title: t("employee.view.table") },
            ]}
          />
        </div>

        {filters.tab === "workflow" ? (
          <WorkflowEmptyState />
        ) : error ? (
          <div className={styles.empty}>
            <span className={`pg-tile ${styles.emptyTile}`} data-tone="red">
              <Users size={24} />
            </span>
            <div className={styles.emptyTitle}>{t("employee.loadFailed")}</div>
            <p className={styles.emptyDesc}>{error}</p>
            <Button onClick={() => void reload()}>{t("employee.retry")}</Button>
          </div>
        ) : view === "table" ? (
          <>
            {isAdmin && selectedRows.length > 0 ? (
              <div className={styles.batchBar}>
                <span className={styles.batchCount}>
                  {t("employee.batch.selected", { count: selectedRows.length })}
                </span>
                <Button
                  size="small"
                  icon={<ShieldCheck size={14} />}
                  onClick={() => {
                    setGovernTargets(selectedRows);
                    setGovernOpen(true);
                  }}
                >
                  {t("employee.batch.govern")}
                </Button>
                <Button
                  size="small"
                  type="text"
                  onClick={() => setSelectedIds([])}
                >
                  {t("employee.batch.clear")}
                </Button>
              </div>
            ) : null}
            <GovernanceTable
              rows={filtered}
              loading={loading}
              canGovern={isAdmin}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              onOpen={openEmployee}
              onGovernance={(employee) => {
                setGovernTargets([employee]);
                setGovernOpen(true);
              }}
              onEdit={(employee) => void modals.openEdit(toAgentSummary(employee))}
              onCopy={(employee) => modals.openCopy(toAgentSummary(employee))}
              onToggle={(employee) => void handleToggle(employee)}
              onDelete={(employee) => void handleDelete(employee)}
            />
          </>
        ) : loading ? (
          <div className={styles.skeletonGrid}>
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className={styles.skeletonCard} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className={styles.empty}>
            <span className={`pg-tile ${styles.emptyTile}`} data-tone="blue">
              <Users size={24} />
            </span>
            <div className={styles.emptyTitle}>
              {t("employee.empty.title")}
            </div>
            <p className={styles.emptyDesc}>{t("employee.empty.desc")}</p>
          </div>
        ) : grouped ? (
          groupedByDepartment.map((group) => (
            <section key={group.departmentId || "__unassigned"} className={styles.groupBlock}>
              <header className={styles.groupHead}>
                <span className={styles.groupName}>
                  {group.departmentName || t("employee.group.unassigned")}
                </span>
                <span className={styles.groupCount}>{group.items.length}</span>
              </header>
              <div className={styles.grid}>
                {group.items.map((employee) => renderCard(employee))}
              </div>
            </section>
          ))
        ) : (
          <div className={styles.grid}>
            {filtered.map((employee) => renderCard(employee))}
          </div>
        )}
      </div>

      <GovernanceModal
        open={governOpen}
        targets={governTargets}
        departments={departments}
        onCancel={() => setGovernOpen(false)}
        onSubmit={submitGovernance}
      />

      <AgentModal
        open={modals.modalVisible}
        editingAgent={modals.editingAgent}
        form={modals.form}
        selectedSkills={modals.selectedSkills}
        onSelectedSkillsChange={modals.setSelectedSkills}
        onInstalledSkillsLoaded={modals.onInstalledSkillsLoaded}
        modelSettings={modals.modelSettings}
        modelSettingsResetToken={modals.modelSettingsResetToken}
        onModelSettingsChange={modals.onModelSettingsChange}
        onSave={modals.submit}
        onCancel={modals.closeModal}
      />

      <CopyAgentModal
        open={modals.copyModalVisible}
        sourceAgent={modals.copyingAgent}
        confirmLoading={modals.copying}
        onOk={modals.copy}
        onCancel={modals.closeCopyModal}
      />
    </div>
  );
}
