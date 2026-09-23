/**
 * TeamDetailPage — 专家团队详情页（/agents/teams/:teamId）。
 *
 * Console 侧的配置工作台：概览（状态/版本/发布预检）+ 成员职责
 * （能力矩阵）+ 协作流程（DAG 编辑）+ Harness 治理（RunPolicy）。
 * 业务枚举与默认限额来自后端 metadata；编辑统一经父级 Form 保存
 * （一个保存入口，避免多处维护配置状态）。运行观察在 XianWork
 * RunDetail，此处不重复运行状态。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { adminExpertTeamsApi } from "../../../api/modules/admin";
import type {
  ExpertTeamRecord,
  MemberUpdateItem,
  TeamCapabilityMember,
  TeamMetadata,
  TeamValidateResult,
  TeamVersionRow,
} from "../../../api/modules/admin";
import MemberResponsibilities from "./team-detail/MemberResponsibilities";
import TeamWorkflowEditor from "./team-detail/TeamWorkflowEditor";
import TeamPolicyForm, {
  POLICY_FIELD_PREFIX,
} from "./team-detail/TeamPolicyForm";
import styles from "@/pages/Admin/admin.module.less";

/** orchestration spec → 详情页表单回填值（与列表页弹窗同约定）。
 *  runtime_enabled 缺省使用 metadata 默认值（后端唯一来源）。 */
function orchToFormValues(
  orch: Record<string, unknown> | null | undefined,
  defaultRuntimeEnabled = true,
) {
  const spec = orch ?? {};
  const policy = (spec.policy ?? {}) as Record<string, number>;
  const runtimeEnabled =
    typeof spec.runtime_enabled === "boolean"
      ? spec.runtime_enabled
      : defaultRuntimeEnabled;
  const values: Record<string, unknown> = {
    [`${POLICY_FIELD_PREFIX}enabled`]: runtimeEnabled,
    [`${POLICY_FIELD_PREFIX}nodes`]:
      Array.isArray(spec.nodes) && spec.nodes.length > 0
        ? JSON.stringify(spec.nodes, null, 2)
        : "",
    [`${POLICY_FIELD_PREFIX}fast_enabled`]:
      Array.isArray(spec.fast_nodes) && spec.fast_nodes.length > 0,
    [`${POLICY_FIELD_PREFIX}fast_nodes`]:
      Array.isArray(spec.fast_nodes) && spec.fast_nodes.length > 0
        ? JSON.stringify(spec.fast_nodes, null, 2)
        : "",
    [`${POLICY_FIELD_PREFIX}plan_note`]:
      typeof spec.plan_note === "string" ? spec.plan_note : "",
  };
  for (const name of [
    "max_repair_per_node",
    "max_replan",
    "max_total_seconds",
    "max_total_tokens",
    "parallelism",
  ]) {
    values[`${POLICY_FIELD_PREFIX}${name}`] = policy[name];
  }
  return values;
}

/** 表单值 → orchestration spec（保存前组装；校验已由 Form 保证）。
 *  无损保存：先展开当前 orchestration 保留治理字段（schema_version /
 *  require_plan_approval 等表单未管理的字段），再覆盖表单管理字段。 */
function buildOrchestration(
  values: Record<string, unknown>,
  currentOrch?: Record<string, unknown> | null,
) {
  const policy: Record<string, number> = {};
  for (const name of [
    "max_repair_per_node",
    "max_replan",
    "max_total_seconds",
    "max_total_tokens",
    "parallelism",
  ]) {
    const raw = values[`${POLICY_FIELD_PREFIX}${name}`];
    policy[name] = typeof raw === "number" ? raw : Number(raw ?? 0);
  }
  const parseNodesText = (text: unknown): unknown[] => {
    const trimmed = typeof text === "string" ? text.trim() : "";
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };
  // 无损合并：保留当前 orchestration 中表单未管理的治理字段
  const base = (currentOrch ?? {}) as Record<string, unknown>;
  return {
    ...base,
    runtime_enabled: values[`${POLICY_FIELD_PREFIX}enabled`] === true,
    nodes: parseNodesText(values[`${POLICY_FIELD_PREFIX}nodes`]),
    fast_nodes:
      values[`${POLICY_FIELD_PREFIX}fast_enabled`] === true
        ? parseNodesText(values[`${POLICY_FIELD_PREFIX}fast_nodes`])
        : [],
    policy,
    plan_note:
      typeof values[`${POLICY_FIELD_PREFIX}plan_note`] === "string"
        ? values[`${POLICY_FIELD_PREFIX}plan_note`]
        : "",
  };
}

export default function TeamDetailPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const navigate = useNavigate();
  const { teamId = "" } = useParams();
  const [team, setTeam] = useState<ExpertTeamRecord | null>(null);
  const [metadata, setMetadata] = useState<TeamMetadata | null>(null);
  const [members, setMembers] = useState<TeamCapabilityMember[]>([]);
  const [memberUpdates, setMemberUpdates] = useState<MemberUpdateItem[]>([]);
  const [capLoading, setCapLoading] = useState(false);
  const [capError, setCapError] = useState("");
  const [versions, setVersions] = useState<TeamVersionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validateResult, setValidateResult] =
    useState<TeamValidateResult | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    try {
      const [record, meta, versionRows, upgradeItems] = await Promise.all([
        adminExpertTeamsApi.get(teamId),
        adminExpertTeamsApi.metadata().catch(() => null),
        adminExpertTeamsApi.versions(teamId).catch(() => []),
        adminExpertTeamsApi.memberUpdates(teamId).catch(() => []),
      ]);
      setTeam(record);
      setMetadata(meta);
      setVersions(versionRows);
      setMemberUpdates(upgradeItems);
      form.setFieldsValue({
        name: record.name,
        description: record.description,
        // 有效配置：runtime_enabled 缺省来自 metadata（前端不硬编码 true/false）
        ...orchToFormValues(
          record.orchestration,
          meta?.default_runtime_enabled ?? true,
        ),
      });
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [teamId, form]);

  useEffect(() => {
    if (teamId) load();
  }, [teamId, load]);

  const loadCapabilities = useCallback(async () => {
    setCapLoading(true);
    setCapError("");
    try {
      const view = await adminExpertTeamsApi.capabilities(teamId);
      setMembers(view.members ?? []);
    } catch (err) {
      setCapError(String(err));
    } finally {
      setCapLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    if (teamId) loadCapabilities();
  }, [teamId, loadCapabilities]);

  /** 可升级成员数（绑定版本 < 最新发布版本）。 */
  const upgradableCount = useMemo(
    () => memberUpdates.filter((u) => u.upgradable).length,
    [memberUpdates],
  );

  /** 一键升级：把可升级成员的版本绑定更新到最新发布版本后保存。 */
  const handleUpgradeVersions = async () => {
    if (!team) return;
    setSaving(true);
    try {
      const latestById = new Map(
        memberUpdates.map((u) => [u.expert_id, u.latest_version]),
      );
      // 仅更新可升级成员的绑定，其余成员原样保留（含 null=未指定）
      const membersBody = team.members.map((m) => {
        const latest = latestById.get(m.expert_id);
        const shouldUpgrade =
          m.expert_version != null && latest != null && latest > m.expert_version;
        return {
          expert_id: m.expert_id,
          role_hint: m.role_hint,
          member_role: m.member_role,
          seq: m.seq,
          expert_version: shouldUpgrade ? latest : m.expert_version,
        };
      });
      const record = await adminExpertTeamsApi.update(teamId, {
        members: membersBody,
      });
      setTeam(record);
      message.success(
        t(
          "admin.teamDetail.upgraded",
          "成员版本绑定已升级到最新发布版本",
        ),
      );
      load();
      loadCapabilities();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  /** 保存：基础信息 + 编排/策略统一一次 PATCH（单一保存入口）。 */
  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const record = await adminExpertTeamsApi.update(teamId, {
        name: values.name,
        description: values.description,
        // 无损保存：传入当前 orchestration 保留治理字段
        orchestration: buildOrchestration(values, team?.orchestration),
      });
      setTeam(record);
      message.success(t("admin.teamDetail.saved", "已保存"));
      load();
    } catch (err) {
      message.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  /** 发布预检：配置跨字段 + 成员可用性 + 模板引用。 */
  const handleValidate = async () => {
    try {
      const result = await adminExpertTeamsApi.validate(teamId);
      setValidateResult(result);
    } catch (err) {
      message.error(String(err));
    }
  };

  const handlePublish = async () => {
    try {
      const record = await adminExpertTeamsApi.publish(teamId);
      setTeam(record);
      message.success(t("admin.teamDetail.published", "已发布"));
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  if (loading) {
    return (
      <div className={styles.page}>
        <PageHeader current={t("admin.teamDetail.title", "团队详情")} />
        <Spin style={{ marginTop: 60 }} />
      </div>
    );
  }
  if (notFound || !team) {
    return (
      <div className={styles.page}>
        <PageHeader current={t("admin.teamDetail.title", "团队详情")} />
        <Alert
          type="warning"
          showIcon
          message={t("admin.teamDetail.notFound", "团队不存在或已删除")}
        />
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        current={team.name}
        extra={
          <Space>
            <Button onClick={() => navigate("/agents/teams")}>
              {t("admin.teamDetail.backToList", "返回列表")}
            </Button>
            <Button onClick={handleValidate}>
              {t("admin.teamDetail.validate", "发布预检")}
            </Button>
            <Button
              type="primary"
              ghost
              onClick={handlePublish}
              disabled={team.status === "archived"}
            >
              {t("admin.teamDetail.publish", "发布")}
            </Button>
            <Button type="primary" loading={saving} onClick={handleSave}>
              {t("common.save", "Save")}
            </Button>
          </Space>
        }
      />
      <Descriptions size="small" column={4} style={{ marginBottom: 8 }}>
        <Descriptions.Item label={t("admin.teamDetail.status", "状态")}>
          <Tag
            color={
              team.status === "published"
                ? "green"
                : team.status === "archived"
                  ? "red"
                  : "default"
            }
          >
            {team.status}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label={t("admin.teamDetail.version", "版本")}>
          v{team.version}
        </Descriptions.Item>
        <Descriptions.Item label={t("admin.teamDetail.mode", "模式")}>
          {team.mode}
        </Descriptions.Item>
        <Descriptions.Item label={t("admin.teamsX.members", "成员")}>
          {team.members.length}
        </Descriptions.Item>
      </Descriptions>

      <Form form={form} layout="vertical">
        <Tabs
          items={[
            {
              key: "overview",
              label: t("admin.teamDetail.tabOverview", "概览"),
              children: (
                <div>
                  <Form.Item
                    name="name"
                    label={t("admin.teamsX.name", "名称")}
                    rules={[{ required: true }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="description"
                    label={t("admin.teamsX.description", "描述")}
                  >
                    <Input.TextArea rows={2} />
                  </Form.Item>
                  <Typography.Title level={5}>
                    {t("admin.teamDetail.versions", "发布版本")}
                  </Typography.Title>
                  <Table<TeamVersionRow>
                    rowKey="version"
                    size="small"
                    dataSource={versions}
                    pagination={false}
                    locale={{ emptyText: t("admin.teamDetail.noVersions", "尚未发布过版本") }}
                    columns={[
                      { title: "v", dataIndex: "version", width: 80 },
                      {
                        title: t("admin.teamDetail.publishedBy", "发布人"),
                        dataIndex: "published_by",
                      },
                      {
                        title: t("admin.teamDetail.publishedAt", "发布时间"),
                        dataIndex: "published_at",
                        render: (v: string | null) =>
                          v ? new Date(v).toLocaleString("zh-CN") : "—",
                      },
                    ]}
                  />
                </div>
              ),
            },
            {
              key: "members",
              label: t("admin.teamDetail.tabMembers", "成员职责"),
              children: (
                <div>
                  {upgradableCount > 0 && (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={t(
                        "admin.teamDetail.upgradeHint",
                        "{{n}} 个成员有新发布版本，建议升级绑定后再发布团队",
                        { n: upgradableCount },
                      )}
                      action={
                        <Button
                          size="small"
                          loading={saving}
                          onClick={handleUpgradeVersions}
                        >
                          {t("admin.teamDetail.upgradeAll", "全部升级到最新")}
                        </Button>
                      }
                    />
                  )}
                  <MemberResponsibilities
                    members={members}
                    upgrades={memberUpdates}
                    loading={capLoading}
                    error={capError}
                  />
                </div>
              ),
            },
            {
              key: "workflow",
              label: t("admin.teamDetail.tabWorkflow", "协作流程"),
              children: <TeamWorkflowEditor form={form} />,
            },
            {
              key: "policy",
              label: t("admin.teamDetail.tabPolicy", "Harness 治理"),
              children: <TeamPolicyForm form={form} metadata={metadata} />,
            },
          ]}
        />
      </Form>

      <Modal
        title={t("admin.teamDetail.validateTitle", "发布预检结果")}
        open={validateResult !== null}
        onCancel={() => setValidateResult(null)}
        footer={
          <Button type="primary" onClick={() => setValidateResult(null)}>
            {t("common.close", "Close")}
          </Button>
        }
      >
        {validateResult && (
          <div>
            {validateResult.ok ? (
              <Alert
                type="success"
                showIcon
                message={t("admin.teamDetail.validateOk", "预检通过，可发布")}
              />
            ) : (
              <Alert
                type="error"
                showIcon
                message={t("admin.teamDetail.validateIssues", "存在以下阻塞问题")}
                description={
                  <ul style={{ paddingLeft: 18, margin: 0 }}>
                    {validateResult.issues.map((issue: string, i: number) => (
                      <li key={i}>{issue}</li>
                    ))}
                  </ul>
                }
              />
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
