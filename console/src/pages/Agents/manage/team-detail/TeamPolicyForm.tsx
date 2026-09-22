/**
 * TeamPolicyForm — Harness 治理策略编辑（团队详情页 Tab）。
 *
 * RunPolicy 数值边界与默认值全部来自后端 metadata（limits），前端
 * 不硬编码业务枚举；runtime_enabled 决定编排是否生效（关闭 = 纯
 * router/pipeline 模式，不进入 workforce 运行时）。
 */
import { Form, InputNumber, Switch, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { TeamMetadata } from "../../../../api/modules/admin/expertTeams";

/** policy 数值字段定义（name 与后端 contracts.RunPolicy 一致）。 */
const POLICY_FIELDS: {
  name: string;
  limitKey: keyof TeamMetadata["limits"];
  min: number;
  max: number;
}[] = [
  {
    name: "max_repair_per_node",
    limitKey: "default_max_repair_per_node",
    min: 0,
    max: 10,
  },
  { name: "max_replan", limitKey: "default_max_replan", min: 0, max: 10 },
  {
    name: "max_total_seconds",
    limitKey: "default_max_total_seconds",
    min: 60,
    max: 86400,
  },
  {
    name: "max_total_tokens",
    limitKey: "default_max_total_tokens",
    min: 0,
    max: 100_000_000,
  },
  { name: "parallelism", limitKey: "default_parallelism", min: 1, max: 8 },
];

export interface TeamPolicyFormProps {
  /** antd Form 实例（父级持有，保存时统一 validateFields）。 */
  form: ReturnType<typeof Form.useForm>[0];
  /** 后端 metadata（默认限额来源；未加载时用保守缺省）。 */
  metadata: TeamMetadata | null;
}

/** 表单字段名前缀（与父级 buildSpec 的拆解约定一致）。 */
export const POLICY_FIELD_PREFIX = "orch_";

export default function TeamPolicyForm({ form, metadata }: TeamPolicyFormProps) {
  const { t } = useTranslation();
  const limits = metadata?.limits;
  const enabled = Form.useWatch(`${POLICY_FIELD_PREFIX}enabled`, form);

  const fieldLabel = (name: string) => {
    switch (name) {
      case "max_repair_per_node":
        return t("admin.teamDetail.policyMaxRepair", "单节点最大返工");
      case "max_replan":
        return t("admin.teamDetail.policyMaxReplan", "最大重规划");
      case "max_total_seconds":
        return t("admin.teamDetail.policyMaxSeconds", "时限（秒）");
      case "max_total_tokens":
        return t("admin.teamDetail.policyMaxTokens", "token 预算（0=不限）");
      case "parallelism":
        return t("admin.teamDetail.policyParallelism", "并行度");
      default:
        return name;
    }
  };

  return (
    <div>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        {t(
          "admin.teamDetail.policyHint",
          "Harness 治理策略是该团队每次运行的熔断上限：返工/重规划次数、时限与 token 预算超限即熔断升级人工；并行度限制同时派发的成员数。默认值来自平台元数据。",
        )}
      </Typography.Paragraph>
      <Form.Item
        name={`${POLICY_FIELD_PREFIX}enabled`}
        label={t("admin.teamDetail.policyEnabled", "启用运行时编排")}
        valuePropName="checked"
        extra={t(
          "admin.teamDetail.policyEnabledExtra",
          "关闭后该团队回到 router/pipeline 基础模式，不走 DAG 编排",
        )}
      >
        <Switch />
      </Form.Item>
      {enabled !== false && (
        <>
          {POLICY_FIELDS.map((field) => (
            <Form.Item
              key={field.name}
              name={`${POLICY_FIELD_PREFIX}${field.name}`}
              label={`${t("admin.teamDetail.policyTitle", "RunPolicy")} · ${fieldLabel(field.name)}`}
              initialValue={limits ? limits[field.limitKey] : undefined}
            >
              <InputNumber
                min={field.min}
                max={field.max}
                style={{ width: 180 }}
              />
            </Form.Item>
          ))}
        </>
      )}
    </div>
  );
}
