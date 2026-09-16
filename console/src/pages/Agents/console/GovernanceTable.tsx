/**
 * Agents/console/GovernanceTable.tsx — 治理表格视图（批量授权的操作面）。
 *
 * 卡片视图负责"看得清"，表格视图负责"管得快"：一屏看全形态 / 归属部门 /
 * 可见范围 / 共享部门，多选后批量下发治理态。所有列居中（全站表格规范），
 * 枚举列一律渲染 i18n 描述文本，不暴露 code。
 */
import { useTranslation } from "react-i18next";
import { Button, Dropdown, Space, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ArrowRight,
  MoreHorizontal,
  ShieldCheck,
} from "lucide-react";
import ExpertAvatar from "@/components/ExpertAvatar";
import { avatarGradient } from "@/utils/avatarGradient";
import type { DigitalEmployee } from "@/api/modules/employeeRegistry";
import { KindBadge, StatusBadge, VisibilityBadge } from "./employeeBadges";
import styles from "./console.module.less";

export interface GovernanceTableProps {
  rows: DigitalEmployee[];
  loading: boolean;
  /** 治理动作（归属/可见性）仅管理员可写。 */
  canGovern: boolean;
  selectedIds: string[];
  onSelectionChange: (ids: string[]) => void;
  onOpen: (employee: DigitalEmployee) => void;
  onGovernance: (employee: DigitalEmployee) => void;
  onToggle?: (employee: DigitalEmployee) => void;
  onCopy?: (employee: DigitalEmployee) => void;
  onDelete?: (employee: DigitalEmployee) => void;
  onEdit?: (employee: DigitalEmployee) => void;
}

function RowAvatar({ employee }: { employee: DigitalEmployee }) {
  if (employee.entity_kind === "expert") {
    return (
      <ExpertAvatar
        icon={employee.icon}
        expertId={employee.entity_id}
        name={employee.name}
        size={28}
      />
    );
  }
  return (
    <span
      style={{
        width: 28,
        height: 28,
        flexShrink: 0,
        borderRadius: "50%",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontSize: 12,
        fontWeight: 600,
        background: avatarGradient(employee.agent_id + employee.name),
      }}
    >
      {(employee.name || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

export function GovernanceTable({
  rows,
  loading,
  canGovern,
  selectedIds,
  onSelectionChange,
  onOpen,
  onGovernance,
  onToggle,
  onCopy,
  onDelete,
  onEdit,
}: GovernanceTableProps) {
  const { t } = useTranslation();

  const columns: ColumnsType<DigitalEmployee> = [
    {
      title: t("employee.table.colName"),
      dataIndex: "name",
      key: "name",
      align: "center",
      fixed: "left",
      width: 240,
      render: (_, employee) => (
        <div className={styles.cellName}>
          <RowAvatar employee={employee} />
          <span
            className={styles.cellNameText}
            title={employee.description || employee.name}
          >
            {employee.name}
          </span>
        </div>
      ),
    },
    {
      title: t("employee.table.colKind"),
      dataIndex: "entity_kind",
      key: "entity_kind",
      align: "center",
      width: 110,
      render: (_, employee) => <KindBadge kind={employee.entity_kind} />,
      filters: [
        { text: t("employee.kind.agent"), value: "agent" },
        { text: t("employee.kind.expert"), value: "expert" },
        { text: t("employee.kind.team"), value: "team" },
      ],
      onFilter: (value, employee) => employee.entity_kind === value,
    },
    {
      title: t("employee.table.colDepartment"),
      dataIndex: "department_name",
      key: "department_name",
      align: "center",
      width: 150,
      render: (_, employee) =>
        employee.department_name || (
          <span style={{ color: "var(--pg-ink-3)" }}>
            {t("employee.group.unassigned")}
          </span>
        ),
    },
    {
      title: t("employee.table.colVisibility"),
      dataIndex: "visibility",
      key: "visibility",
      align: "center",
      width: 180,
      render: (_, employee) =>
        employee.governed ? (
          <VisibilityBadge employee={employee} />
        ) : (
          // 未治理行还没有可见范围决策，此处留空比沿用默认语义更诚实
          <span style={{ color: "var(--pg-ink-3)" }}>—</span>
        ),
    },
    {
      title: t("employee.table.colShared"),
      dataIndex: "granted_department_names",
      key: "granted_department_names",
      align: "center",
      width: 180,
      render: (_, employee) =>
        employee.granted_department_names.length ? (
          <Tooltip
            title={employee.granted_department_names.join("、")}
          >
            <span>
              {employee.granted_department_names.slice(0, 2).join("、")}
              {employee.granted_department_names.length > 2
                ? ` +${employee.granted_department_names.length - 2}`
                : ""}
            </span>
          </Tooltip>
        ) : (
          <span style={{ color: "var(--pg-ink-3)" }}>—</span>
        ),
    },
    {
      title: t("employee.table.colStatus"),
      dataIndex: "startup_status",
      key: "startup_status",
      align: "center",
      width: 110,
      render: (_, employee) => <StatusBadge employee={employee} />,
    },
    {
      title: t("employee.table.colModel"),
      dataIndex: "model_label",
      key: "model_label",
      align: "center",
      width: 170,
      render: (value: string) =>
        value || <span style={{ color: "var(--pg-ink-3)" }}>—</span>,
    },
    {
      title: t("employee.table.colMembers"),
      dataIndex: "member_count",
      key: "member_count",
      align: "center",
      width: 90,
      render: (value: number, employee) =>
        employee.entity_kind === "team" ? value : "—",
    },
    {
      title: t("employee.table.colActions"),
      key: "actions",
      align: "center",
      fixed: "right",
      width: 150,
      render: (_, employee) => (
        <Space size={2} onClick={(event) => event.stopPropagation()}>
          <Tooltip title={t("employee.action.enterWorkbench")}>
            <Button
              type="text"
              size="small"
              aria-label={t("employee.action.enterWorkbench")}
              onClick={() => onOpen(employee)}
            >
              <ArrowRight size={15} />
            </Button>
          </Tooltip>
          {canGovern ? (
            <Tooltip title={t("employee.action.governance")}>
              <Button
                type="text"
                size="small"
                aria-label={t("employee.action.governance")}
                onClick={() => onGovernance(employee)}
              >
                <ShieldCheck size={15} />
              </Button>
            </Tooltip>
          ) : null}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                onEdit
                  ? { key: "edit", label: t("employee.action.capabilities") }
                  : null,
                onCopy ? { key: "copy", label: t("common.copy") } : null,
                onToggle
                  ? {
                      key: "toggle",
                      label: employee.enabled
                        ? t("common.disable")
                        : t("common.enable"),
                    }
                  : null,
                onDelete
                  ? {
                      key: "delete",
                      label: t("common.delete"),
                      danger: true,
                    }
                  : null,
              ].filter(Boolean) as { key: string; label: string; danger?: boolean }[],
              onClick: ({ key }) => {
                if (key === "edit") onEdit?.(employee);
                else if (key === "copy") onCopy?.(employee);
                else if (key === "toggle") onToggle?.(employee);
                else if (key === "delete") onDelete?.(employee);
              },
            }}
          >
            <Button type="text" size="small" aria-label={t("common.actions")}>
              <MoreHorizontal size={15} />
            </Button>
          </Dropdown>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.tableWrap}>
      <Table<DigitalEmployee>
        rowKey="agent_id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1360 }}
        rowSelection={
          canGovern
            ? {
                selectedRowKeys: selectedIds,
                onChange: (keys) => onSelectionChange(keys as string[]),
                columnWidth: 44,
              }
            : undefined
        }
        onRow={(employee) => ({
          onClick: () => onOpen(employee),
          style: { cursor: "pointer" },
        })}
      />
    </div>
  );
}
