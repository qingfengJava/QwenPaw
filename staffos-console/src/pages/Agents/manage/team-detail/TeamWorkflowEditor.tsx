/**
 * TeamWorkflowEditor — 协作流程编辑（团队详情页 Tab）。
 *
 * DAG 节点模板 / 快速链 / 计划备注的编辑入口：与列表页弹窗编辑共用
 * 同一 schema（node_key/deps/assignee/node_type/objective），此处负责
 * 详情页视角的编辑与波次预览；表单值经父级 Form 统一保存，不在此
 * 单独提交（避免两处维护保存逻辑）。
 */
import { Form, Input, Switch, Typography } from "antd";
import { useTranslation } from "react-i18next";
import WavePreview from "../WavePreview";
import { POLICY_FIELD_PREFIX } from "./TeamPolicyForm";

/** 校验 nodes/fast_nodes JSON：数组、node_key 非空唯一、deps 可解析。 */
function validateNodesJson(
  _rule: unknown,
  value: string | undefined,
): Promise<void> {
  const text = (value ?? "").trim();
  if (!text) return Promise.resolve();
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) {
      return Promise.reject(new Error("协作流程必须是 JSON 数组（节点列表）"));
    }
    const bad = parsed.find(
      (n) =>
        !n ||
        typeof n !== "object" ||
        typeof n.node_key !== "string" ||
        !n.node_key,
    );
    if (bad !== undefined) {
      return Promise.reject(new Error("每个节点必须包含非空 node_key 字段"));
    }
    const keys = new Set(parsed.map((n) => n.node_key));
    if (keys.size !== parsed.length) {
      return Promise.reject(new Error("node_key 存在重复"));
    }
    for (const node of parsed) {
      for (const dep of node.deps ?? []) {
        if (!keys.has(dep)) {
          return Promise.reject(
            new Error(`节点 ${node.node_key} 依赖了未定义的 ${dep}`),
          );
        }
      }
    }
    return Promise.resolve();
  } catch {
    return Promise.reject(new Error("JSON 语法错误"));
  }
}

export interface TeamWorkflowEditorProps {
  /** antd Form 实例（父级持有；字段名前缀与 TeamPolicyForm 一致）。 */
  form: ReturnType<typeof Form.useForm>[0];
}

export default function TeamWorkflowEditor({ form }: TeamWorkflowEditorProps) {
  const { t } = useTranslation();
  const nodesJson = Form.useWatch(`${POLICY_FIELD_PREFIX}nodes`, form);
  const fastEnabled = Form.useWatch(`${POLICY_FIELD_PREFIX}fast_enabled`, form);
  const fastNodesJson = Form.useWatch(`${POLICY_FIELD_PREFIX}fast_nodes`, form);

  return (
    <div>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {t(
          "admin.teamDetail.workflowHint",
          "协作流程决定成员如何接力：预置 DAG 模板时规划器按模板派发（模板优先）；留空则由中央大脑（主理人）按需求单次规划。多个节点写相同 deps 即并行执行。",
        )}
      </Typography.Paragraph>
      <Form.Item
        name={`${POLICY_FIELD_PREFIX}nodes`}
        label={t("admin.teamDetail.workflowNodes", "DAG 节点模板（JSON 数组，留空 = 中央大脑规划）")}
        extra={t(
          "admin.teamDetail.workflowNodesExtra",
          "节点字段：node_key / deps / assignee_expert_id / node_type（task|integration|final）/ objective / expected_output。final 节点由中央大脑汇总。",
        )}
        rules={[{ validator: validateNodesJson }]}
      >
        <Input.TextArea
          rows={10}
          style={{ fontFamily: "monospace", fontSize: 12 }}
        />
      </Form.Item>
      <Form.Item
        label={t("admin.teamDetail.workflowPreview", "波次预览（标准链）")}
        style={{ marginBottom: 16 }}
      >
        <WavePreview
          nodesJson={nodesJson}
          emptyHint={t("admin.teamDetail.workflowEmpty", "尚未配置节点（留空 = 中央大脑规划）")}
        />
      </Form.Item>
      <Form.Item
        name={`${POLICY_FIELD_PREFIX}fast_enabled`}
        label={t("admin.teamDetail.workflowFastEnabled", "启用快速链（小需求精简流程）")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      {fastEnabled && (
        <>
          <Form.Item
            name={`${POLICY_FIELD_PREFIX}fast_nodes`}
            label={t("admin.teamDetail.workflowFastNodes", "快速链节点模板（独立完整 DAG，需含 final 汇总节点）")}
            rules={[{ validator: validateNodesJson }]}
          >
            <Input.TextArea
              rows={8}
              style={{ fontFamily: "monospace", fontSize: 12 }}
            />
          </Form.Item>
          <Form.Item
            label={t("admin.teamDetail.workflowFastPreview", "波次预览（快速链）")}
            style={{ marginBottom: 16 }}
          >
            <WavePreview
              nodesJson={fastNodesJson}
              emptyHint={t("admin.teamDetail.workflowFastEmpty", "尚未配置快速链节点")}
            />
          </Form.Item>
        </>
      )}
      <Form.Item
        name={`${POLICY_FIELD_PREFIX}plan_note`}
        label={t("admin.teamDetail.workflowPlanNote", "计划备注（plan_note）")}
      >
        <Input.TextArea rows={2} />
      </Form.Item>
    </div>
  );
}
