/**
 * Admin/Experts — 数字员工列表页（StaffDeck 设计语言重构，20260830）。
 *
 * 结构：统计卡行（总数/在线/草稿 + 新建入口）→ 状态 UnderlineTabs +
 * 搜索 → EmployeeCard 网格（点击进详情页）。保留既有生命周期操作：
 * 新建/编辑（含档案字段）/发布/归档/删除。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Divider,
  Dropdown,
  Form,
  Input,
  Modal,
  Space,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import ExpertAvatarPicker from "@/components/ExpertAvatarPicker";
import {
  EmployeeCard,
  StatCard,
  UnderlineTabs,
} from "@/components/staffdeck";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { openAgentWorkbench } from "@/utils/openAgentWorkbench";
import {
  adminExpertsApi,
  expertCapabilityApi,
  type CapabilityCounts,
} from "../../../api/modules/admin";
import type { ExpertRecord } from "../../../api/modules/admin";
import {
  SampleTasksEditor,
  ShowcaseEditor,
  normalizeShowcase,
} from "./OperationsFields";

type StatusFilter = "all" | "published" | "draft" | "archived";

function ExpertsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const navigate = useNavigate();
  const [experts, setExperts] = useState<ExpertRecord[]>([]);
  const [counts, setCounts] = useState<Record<string, CapabilityCounts>>({});
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ExpertRecord | "new" | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [form] = Form.useForm();
  // 形象选择器预览用实时名称（新建/编辑时随输入变化）
  const editingName = Form.useWatch("name", form) as string | undefined;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await adminExpertsApi.list();
      setExperts(list);
      // 卡片计数一次批查（无 N+1）
      if (list.length > 0) {
        const res = await expertCapabilityApi.capabilityCounts(
          list.map((e) => e.id),
        );
        setCounts(res.counts ?? {});
      } else {
        setCounts({});
      }
    } catch (err) {
      message.error(t("admin.experts.loadFailed", "Failed to load experts"));
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openEditor = (expert: ExpertRecord | "new") => {
    setEditing(expert);
    form.setFieldsValue(
      expert === "new"
        ? {
            name: "",
            icon: "",
            description: "",
            agent_spec: "{}",
            sample_tasks: [],
            showcase: [],
            work_styles_text: "",
            work_modes_text: "",
          }
        : {
            name: expert.name,
            icon: expert.icon,
            title: expert.title,
            department: expert.department,
            description: expert.description,
            agent_spec: JSON.stringify(expert.agent_spec, null, 2),
            sample_tasks: expert.sample_tasks ?? [],
            // tags 回填为逗号串（编辑器输入形态）
            showcase: (expert.showcase ?? []).map((c) => ({
              ...c,
              tags: (c.tags ?? []).join(","),
            })),
            work_styles_text: (expert.work_styles ?? []).join("，"),
            work_modes_text: (expert.work_modes ?? []).join("，"),
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    let spec: Record<string, unknown>;
    try {
      spec = JSON.parse(values.agent_spec || "{}");
    } catch {
      message.error(
        t("admin.experts.badJson", "agent_spec must be valid JSON"),
      );
      return;
    }
    const sampleTasks = (values.sample_tasks ?? []).filter(
      (item: { title?: string; prompt?: string }) =>
        (item.title ?? "").trim() && (item.prompt ?? "").trim(),
    );
    const showcase = normalizeShowcase(values.showcase).filter(
      (item) => item.title.trim() && item.desc.trim(),
    );
    // 档案字段：逗号/顿号分隔输入 → 数组
    const splitList = (text: string | undefined) =>
      (text ?? "")
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean);
    const profile = {
      title: values.title ?? "",
      department: values.department ?? "",
      work_styles: splitList(values.work_styles_text),
      work_modes: splitList(values.work_modes_text),
    };
    try {
      if (editing === "new") {
        await adminExpertsApi.create({
          name: values.name,
          icon: values.icon ?? "",
          description: values.description ?? "",
          agent_spec: spec,
          sample_tasks: sampleTasks,
          showcase,
          ...profile,
        });
      } else if (editing) {
        await adminExpertsApi.update(editing.id, {
          name: values.name,
          icon: values.icon,
          description: values.description,
          agent_spec: spec,
          sample_tasks: sampleTasks,
          showcase,
          ...profile,
        });
      }
      message.success(t("admin.experts.saved", "Expert saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handlePublish = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.publish(expert.id);
      message.success(
        t("admin.experts.published", "Expert published to XianWork"),
      );
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleArchive = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.archive(expert.id);
      message.success(t("admin.experts.archived", "Expert archived"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (expert: ExpertRecord) => {
    try {
      await adminExpertsApi.remove(expert.id);
      message.success(t("admin.experts.deleted", "Draft deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return experts.filter((e) => {
      if (filter !== "all" && e.status !== filter) return false;
      if (!kw) return true;
      return (
        e.name.toLowerCase().includes(kw)
        || (e.title ?? "").toLowerCase().includes(kw)
        || (e.description ?? "").toLowerCase().includes(kw)
      );
    });
  }, [experts, filter, keyword]);

  const publishedCount = experts.filter((e) => e.status === "published").length;
  const draftCount = experts.filter((e) => e.status === "draft").length;

  const cardMenu = (expert: ExpertRecord) => (
    <Dropdown
      menu={{
        items: [
          { key: "edit", label: t("common.edit", "Edit") },
          ...(expert.status !== "archived"
            ? [{ key: "publish", label: t("admin.experts.publish", "Publish") }]
            : []),
          ...(expert.status === "published"
            ? [{ key: "archive", label: t("admin.experts.archive", "Archive") }]
            : []),
          ...(expert.status === "draft"
            ? [{ key: "delete", label: t("common.delete", "Delete"), danger: true }]
            : []),
        ],
        onClick: ({ key }) => {
          if (key === "edit") openEditor(expert);
          else if (key === "publish") void handlePublish(expert);
          else if (key === "archive") void handleArchive(expert);
          else if (key === "delete") {
            void handleDelete(expert);
          }
        },
      }}
    >
      <Button type="text" size="small">
        ···
      </Button>
    </Dropdown>
  );

  return (
    <div className="sd-page">
      <PageHeader
        parent={t("nav.employees", "Digital Employees")}
        current={t("nav.agentsManage", "Manage Employees")}
      />

      {/* 统计卡行 */}
      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <StatCard
          value={experts.length}
          label={t("staffdeck.experts.total", "员工总数")}
          onClick={() => setFilter("all")}
        />
        <StatCard
          value={publishedCount}
          label={t("staffdeck.experts.published", "在线员工")}
          tone="green"
          onClick={() => setFilter("published")}
        />
        <StatCard
          value={draftCount}
          label={t("staffdeck.experts.draft", "草稿员工")}
          onClick={() => setFilter("draft")}
        />
        <StatCard
          value="+"
          label={t("staffdeck.experts.create", "创建新员工")}
          sublabel={t("staffdeck.experts.createHint", "几步搭好你的数字员工")}
          onClick={() => openEditor("new")}
        />
      </div>

      {/* 筛选行：状态 Tabs + 搜索 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          margin: "28px 0 20px",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <UnderlineTabs
          items={[
            { key: "all", label: t("staffdeck.experts.tabAll", "全部员工"), count: experts.length },
            { key: "published", label: t("staffdeck.experts.tabOnline", "在线员工"), count: publishedCount },
            { key: "draft", label: t("staffdeck.experts.tabDraft", "草稿"), count: draftCount },
            {
              key: "archived",
              label: t("staffdeck.experts.tabArchived", "已归档"),
              count: experts.filter((e) => e.status === "archived").length,
            },
          ]}
          value={filter}
          onChange={(key) => setFilter(key as StatusFilter)}
        />
        <Input.Search
          allowClear
          placeholder={t("staffdeck.experts.search", "搜索员工…")}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ maxWidth: 320 }}
        />
      </div>

      {/* 员工卡片网格 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 24,
        }}
      >
        {visible.map((expert) => {
          const c = counts[expert.id] ?? {
            resources: 0,
            skills: 0,
            sops: 0,
            scheduled_tasks: 0,
          };
          return (
            <EmployeeCard
              key={expert.id}
              expert={{
                id: expert.id,
                name: expert.name,
                title: expert.title,
                description: expert.description,
                status: expert.status,
                department: expert.department,
                work_styles: expert.work_styles,
                work_modes: expert.work_modes,
                badge: expert.badge,
              }}
              counts={{
                resources: c.resources,
                skills: c.skills,
                sops: c.sops,
                scheduledTasks: c.scheduled_tasks,
              }}
              onClick={() => {
                // 已发布员工进工作台（运行时 agent id = expert_{id}，
                // 新标签页打开）；草稿无运行时实例，仍进管理详情页。
                if (expert.status === "published") {
                  openAgentWorkbench(`expert_${expert.id}`);
                  return;
                }
                navigate(`/agents/manage/${expert.id}`);
              }}
              extraMenu={cardMenu(expert)}
            />
          );
        })}
        {visible.length === 0 && !loading ? (
          <div
            className="sd-card"
            style={{
              gridColumn: "1 / -1",
              padding: "48px 0",
              textAlign: "center",
              color: "var(--sd-text-3)",
              borderStyle: "dashed",
            }}
          >
            {t("staffdeck.experts.empty", "暂无员工，点击右上角「创建新员工」开始")}
          </div>
        ) : null}
      </div>

      {/* 新建/编辑弹窗（保留既有 CRUD + 档案字段） */}
      <Modal
        title={
          editing === "new"
            ? t("admin.experts.create", "New expert")
            : t("admin.experts.edit", "Edit expert")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.experts.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Space size="middle" style={{ display: "flex" }}>
            <Form.Item
              name="icon"
              label={t("admin.experts.icon", "形象")}
              tooltip={t(
                "admin.experts.iconHint",
                "选择形象风格；恢复自动则按员工 ID 稳定分配",
              )}
            >
              <ExpertAvatarPicker
                expertId={
                  editing !== "new" && editing ? editing.id : undefined
                }
                name={editingName}
              />
            </Form.Item>
            <Form.Item
              name="title"
              label={t("staffdeck.experts.jobTitle", "职称")}
            >
              <Input
                placeholder={t(
                  "staffdeck.experts.jobTitlePlaceholder",
                  "如：高级客户经理",
                )}
                style={{ width: 220 }}
              />
            </Form.Item>
          </Space>
          <Space size="middle" style={{ display: "flex" }}>
            <Form.Item
              name="department"
              label={t("staffdeck.experts.department", "部门")}
            >
              <Input style={{ width: 160 }} />
            </Form.Item>
            <Form.Item
              name="work_styles_text"
              label={t("staffdeck.experts.workStyles", "工作风格（逗号分隔）")}
            >
              <Input
                placeholder={t(
                  "staffdeck.experts.workStylesPlaceholder",
                  "耐心细致，结果导向",
                )}
                style={{ width: 260 }}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="work_modes_text"
            label={t("staffdeck.experts.workModes", "工作方式（逗号分隔）")}
          >
            <Input
              placeholder={t(
                "staffdeck.experts.workModesPlaceholder",
                "7x24 值守，定时巡检",
              )}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.experts.description", "Description")}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="agent_spec"
            label={t(
              "admin.experts.spec",
              "Agent spec (agent.json-compatible JSON)",
            )}
            rules={[
              {
                validator: (_, value) => {
                  if (!value) return Promise.resolve();
                  try {
                    JSON.parse(value);
                    return Promise.resolve();
                  } catch {
                    return Promise.reject(new Error("invalid JSON"));
                  }
                },
              },
            ]}
          >
            <Input.TextArea rows={10} style={{ fontFamily: "monospace" }} />
          </Form.Item>
          <Divider orientation="left" plain>
            {t("admin.ops.section", "运营位（专家帮你做 / 使用案例）")}
          </Divider>
          <Form.Item
            label={t(
              "admin.ops.tasks",
              "任务模板（详情页「专家帮你做」，点击即以提示词召唤）",
            )}
          >
            <SampleTasksEditor />
          </Form.Item>
          <Form.Item
            label={t("admin.ops.cases", "使用案例（静态运营位）")}
          >
            <ShowcaseEditor />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExpertsPage;
