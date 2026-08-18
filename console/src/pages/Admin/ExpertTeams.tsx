/**
 * Admin/ExpertTeams — multi-expert orchestration: ordered members,
 * router/pipeline mode, publish to XianWork (Phase 3); workforce
 * orchestration spec editor (preset DAG template JSON + RunPolicy)
 * and the team test-run entry (Phase 3 workforce).
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  adminExpertTeamsApi,
  adminExpertsApi,
  adminWorkforceApi,
} from "../../api/modules/admin";
import type {
  ExpertRecord,
  ExpertTeamRecord,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

/** RunPolicy 数值字段（与后端 contracts.RunPolicy 一致）。 */
const POLICY_FIELDS: {
  name: string;
  label: string;
  min: number;
  max: number;
}[] = [
  { name: "max_repair_per_node", label: "单节点最大返工", min: 0, max: 10 },
  { name: "max_replan", label: "最大重规划", min: 0, max: 10 },
  { name: "max_total_seconds", label: "时限（秒）", min: 60, max: 86400 },
  { name: "max_total_tokens", label: "token 预算（0=不限）", min: 0, max: 100_000_000 },
  { name: "parallelism", label: "波次并行度", min: 1, max: 8 },
];

/** 默认 DAG 节点模板（两节点 + 汇总：编辑器的起步示例）。 */
const DEFAULT_NODES_TEMPLATE = [
  {
    node_key: "node-1",
    deps: [],
    assignee_expert_id: "<expert-id>",
    node_type: "task",
    objective: "节点目标（子员工 TaskContract.objective）",
    expected_output: ["期望产出"],
  },
  {
    node_key: "final-summary",
    deps: ["node-1"],
    node_type: "final",
    objective: "汇总全部上游结果",
  },
];

function ExpertTeamsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [teams, setTeams] = useState<ExpertTeamRecord[]>([]);
  const [experts, setExperts] = useState<ExpertRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<ExpertTeamRecord | "new" | null>(
    null,
  );
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [teamList, expertList] = await Promise.all([
        adminExpertTeamsApi.list(),
        adminExpertsApi.list("published").catch(() => []),
      ]);
      setTeams(teamList);
      setExperts(expertList);
    } catch (err) {
      message.error(t("admin.teamsX.loadFailed", "Failed to load teams"));
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
  }, [load]);

  /**
   * 表单值 → OrchestrationSpec（与后端 contracts.OrchestrationSpec
   * 同一 schema）：nodes 留空表示不预置模板（中央大脑 LLM 规划），
   * policy 始终作为该团队的默认 RunPolicy 生效。
   */
  const buildOrchestration = (values: Record<string, unknown>) => {
    const policy: Record<string, number> = {};
    for (const field of POLICY_FIELDS) {
      const raw = values[`orch_${field.name}`];
      policy[field.name] = typeof raw === "number" ? raw : Number(raw ?? 0);
    }
    // nodes 来自 TextArea（JSON 数组文本，validateFields 已保证合法）
    let nodes: unknown[] = [];
    const nodesText = typeof values.orch_nodes === "string" ? values.orch_nodes.trim() : "";
    if (nodesText) {
      try {
        const parsed = JSON.parse(nodesText);
        if (Array.isArray(parsed)) {
          nodes = parsed;
        }
      } catch {
        // 校验层已拦截；此处兜底忽略（保存的模板为空 = LLM 规划）
      }
    }
    return {
      runtime_enabled: values.orch_enabled === true,
      nodes,
      policy,
      plan_note: typeof values.orch_plan_note === "string" ? values.orch_plan_note : "",
    };
  };

  /** 团队记录 → 编辑表单回填值（orchestration 拆解为表单字段）。 */
  const orchToFormValues = (orch: Record<string, unknown> | null | undefined) => {
    const spec = orch ?? {};
    const policy = (spec.policy ?? {}) as Record<string, number>;
    const values: Record<string, unknown> = {
      orch_enabled: spec.runtime_enabled === true,
      orch_nodes: Array.isArray(spec.nodes) && spec.nodes.length > 0
        ? JSON.stringify(spec.nodes, null, 2)
        : "",
      orch_plan_note: typeof spec.plan_note === "string" ? spec.plan_note : "",
    };
    for (const field of POLICY_FIELDS) {
      values[`orch_${field.name}`] = policy[field.name];
    }
    return values;
  };

  const openEditor = (team: ExpertTeamRecord | "new") => {
    setEditing(team);
    form.setFieldsValue(
      team === "new"
        ? {
            name: "",
            description: "",
            mode: "router",
            router_prompt: "",
            members: [],
            ...orchToFormValues(null),
          }
        : {
            name: team.name,
            description: team.description,
            mode: team.mode,
            router_prompt: team.router_prompt,
            members: team.members.map((m) => m.expert_id),
            ...orchToFormValues(team.orchestration),
          },
    );
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const memberIds: string[] = values.members ?? [];
    const members = memberIds.map((expert_id, index) => ({
      expert_id,
      seq: index,
    }));
    const orchestration = buildOrchestration(values);
    try {
      if (editing === "new") {
        await adminExpertTeamsApi.create({
          name: values.name,
          description: values.description ?? "",
          mode: values.mode,
          router_prompt: values.router_prompt ?? "",
          members,
          orchestration,
        });
      } else if (editing) {
        await adminExpertTeamsApi.update(editing.id, {
          name: values.name,
          description: values.description,
          mode: values.mode,
          router_prompt: values.router_prompt,
          members,
          orchestration,
        });
      }
      message.success(t("admin.teamsX.saved", "Team saved"));
      setEditing(null);
      form.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  /**
   * 团队试运行：创建一次测试 run（后台引擎启动），成功后展示
   * run id —— 管理员到 XianWork 任务详情页观察 DAG 执行/验收/
   * 熔断全链路是否符合理想。
   */
  const handleTestRun = async (team: ExpertTeamRecord) => {
    try {
      const run = await adminWorkforceApi.testRun(team.id);
      Modal.info({
        title: t("admin.teamsX.testRunCreated", "Test run created"),
        content: (
          <div>
            <p>
              {t(
                "admin.teamsX.testRunHint",
                "Test run started in the background. Track the DAG progress in XianWork:",
              )}
            </p>
            <Typography.Paragraph copyable={{ text: run.id }}>
              {run.id}
            </Typography.Paragraph>
          </div>
        ),
      });
    } catch (err) {
      message.error(String(err));
    }
  };

  const handlePublish = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.publish(team.id);
      message.success(
        t("admin.teamsX.published", "Team published to XianWork"),
      );
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleArchive = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.archive(team.id);
      message.success(t("admin.teamsX.archived", "Team archived"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDelete = async (team: ExpertTeamRecord) => {
    try {
      await adminExpertTeamsApi.remove(team.id);
      message.success(t("admin.teamsX.deleted", "Team deleted"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const expertName = (id: string) =>
    experts.find((e) => e.id === id)?.name ?? id;

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminExpertTeams", "Expert Teams")}
        extra={
          <Button type="primary" onClick={() => openEditor("new")}>
            {t("admin.teamsX.create", "New expert team")}
          </Button>
        }
      />
      <Table<ExpertTeamRecord>
        rowKey="id"
        loading={loading}
        dataSource={teams}
        pagination={false}
        columns={[
          { title: t("admin.teamsX.name", "Name"), dataIndex: "name" },
          {
            title: t("admin.teamsX.mode", "Mode"),
            dataIndex: "mode",
            width: 110,
            render: (mode: string) => (
              <Tag color={mode === "pipeline" ? "blue" : "purple"}>
                {mode}
              </Tag>
            ),
          },
          {
            title: t("admin.teamsX.members", "Members"),
            dataIndex: "members",
            render: (members: ExpertTeamRecord["members"]) =>
              members.length
                ? members.map((m) => (
                    <Tag key={m.expert_id}>{expertName(m.expert_id)}</Tag>
                  ))
                : "—",
          },
          {
            title: t("admin.teamsX.orchestration", "Orchestration"),
            key: "orchestration",
            width: 120,
            render: (_, team) => {
              const nodes = (team.orchestration?.nodes ?? []) as unknown[];
              if (!team.orchestration?.runtime_enabled) {
                return <Tag>LLM 规划</Tag>;
              }
              return nodes.length
                ? <Tag color="geekblue">DAG × {nodes.length}</Tag>
                : <Tag color="purple">运行时编排</Tag>;
            },
          },
          {
            title: t("admin.teamsX.status", "Status"),
            dataIndex: "status",
            width: 110,
            render: (status: string) => (
              <Tag
                color={
                  status === "published"
                    ? "green"
                    : status === "archived"
                      ? "red"
                      : "default"
                }
              >
                {status}
              </Tag>
            ),
          },
          {
            title: t("admin.teamsX.actions", "Actions"),
            key: "actions",
            width: 340,
            render: (_, team) => (
              <Space>
                <Button size="small" onClick={() => openEditor(team)}>
                  {t("common.edit", "Edit")}
                </Button>
                {team.status === "published" && (
                  <Popconfirm
                    title={t(
                      "admin.teamsX.testRunConfirm",
                      "Start a test run for this team's orchestration?",
                    )}
                    onConfirm={() => handleTestRun(team)}
                  >
                    <Button size="small">试运行</Button>
                  </Popconfirm>
                )}
                {team.status !== "archived" && (
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() => handlePublish(team)}
                  >
                    {t("admin.teamsX.publish", "Publish")}
                  </Button>
                )}
                {team.status === "published" && (
                  <Button size="small" onClick={() => handleArchive(team)}>
                    {t("admin.teamsX.archive", "Archive")}
                  </Button>
                )}
                {team.status === "draft" && (
                  <Popconfirm
                    title={t(
                      "admin.teamsX.deleteConfirm",
                      "Delete this team?",
                    )}
                    onConfirm={() => handleDelete(team)}
                  >
                    <Button size="small" danger>
                      {t("common.delete", "Delete")}
                    </Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={
          editing === "new"
            ? t("admin.teamsX.create", "New expert team")
            : t("admin.teamsX.edit", "Edit expert team")
        }
        open={editing !== null}
        onOk={handleSave}
        onCancel={() => setEditing(null)}
        width={720}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("admin.teamsX.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("admin.teamsX.description", "Description")}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="mode"
            label={t("admin.teamsX.mode", "Orchestration mode")}
          >
            <Select
              options={[
                {
                  value: "router",
                  label: t(
                    "admin.teamsX.modeRouter",
                    "router — pick the best member per turn",
                  ),
                },
                {
                  value: "pipeline",
                  label: t(
                    "admin.teamsX.modePipeline",
                    "pipeline — members run in order (max 3)",
                  ),
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="members"
            label={t(
              "admin.teamsX.members",
              "Member experts (published only, ordered)",
            )}
          >
            <Select
              mode="multiple"
              options={experts.map((e) => ({
                value: e.id,
                label: e.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="router_prompt"
            label={t(
              "admin.teamsX.routerPrompt",
              "Routing guidance (supervisor prompt)",
            )}
          >
            <Input.TextArea rows={3} />
          </Form.Item>

          <Divider orientation="left" plain>
            {t("admin.teamsX.orchSection", "Workforce 编排配置（运行时 DAG）")}
          </Divider>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            {t(
              "admin.teamsX.orchHint",
              "预置 DAG 模板时规划器跳过 LLM 规划（Plan-then-Execute：模板优先）；留空节点则由中央大脑（lead 成员）按需求单次生成。RunPolicy 为该团队的默认熔断策略。",
            )}
          </Typography.Paragraph>
          <Form.Item
            name="orch_enabled"
            label={t(
              "admin.teamsX.orchEnabled",
              "启用运行时编排（runtime_enabled）",
            )}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          {POLICY_FIELDS.map((field) => (
            <Form.Item
              key={field.name}
              name={`orch_${field.name}`}
              label={`${t("admin.teamsX.policy", "RunPolicy")} · ${field.label}`}
              initialValue={
                field.name === "max_total_seconds"
                  ? 3600
                  : field.name === "parallelism"
                    ? 2
                    : field.name === "max_total_tokens"
                      ? 0
                      : field.name === "max_replan"
                        ? 2
                        : 3
              }
            >
              <InputNumber min={field.min} max={field.max} style={{ width: 160 }} />
            </Form.Item>
          ))}
          <Form.Item
            name="orch_nodes"
            label={t(
              "admin.teamsX.orchNodes",
              "DAG 节点模板（JSON 数组，留空 = LLM 规划）",
            )}
            extra={t(
              "admin.teamsX.orchNodesExtra",
              "节点字段：node_key / deps / assignee_expert_id（成员专家 id）/ node_type（task|integration|final）/ objective / expected_output。final 节点由中央大脑自执行汇总。",
            )}
            rules={[
              {
                validator: (_, value: string | undefined) => {
                  const text = (value ?? "").trim();
                  if (!text) return Promise.resolve();
                  try {
                    const parsed = JSON.parse(text);
                    if (!Array.isArray(parsed)) {
                      return Promise.reject(
                        new Error("DAG 模板必须是 JSON 数组（节点列表）"),
                      );
                    }
                    const bad = parsed.find(
                      (n) =>
                        !n ||
                        typeof n !== "object" ||
                        typeof n.node_key !== "string" ||
                        !n.node_key,
                    );
                    if (bad !== undefined) {
                      return Promise.reject(
                        new Error("每个节点必须包含非空 node_key 字段"),
                      );
                    }
                    const keys = new Set(parsed.map((n) => n.node_key));
                    if (keys.size !== parsed.length) {
                      return Promise.reject(new Error("node_key 存在重复"));
                    }
                    for (const node of parsed) {
                      for (const dep of node.deps ?? []) {
                        if (!keys.has(dep)) {
                          return Promise.reject(
                            new Error(
                              `节点 ${node.node_key} 依赖了未定义的 ${dep}`,
                            ),
                          );
                        }
                      }
                    }
                    return Promise.resolve();
                  } catch {
                    return Promise.reject(new Error("JSON 语法错误"));
                  }
                },
              },
            ]}
          >
            <Input.TextArea
              rows={10}
              placeholder={JSON.stringify(DEFAULT_NODES_TEMPLATE, null, 2)}
              style={{ fontFamily: "monospace", fontSize: 12 }}
            />
          </Form.Item>
          <Form.Item
            name="orch_plan_note"
            label={t("admin.teamsX.orchPlanNote", "计划备注（plan_note）")}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default ExpertTeamsPage;
