/**
 * Agents/console/useAgentFormModal.ts — 智能体新建/编辑/复制弹窗逻辑。
 *
 * 从原 AgentsGalleryPage 完整迁出（含邮箱凭据与推送规则的隐藏但保留语义），
 * 控制台与后续任何入口共用同一份表单契约，避免第二份提交逻辑散落。
 */
import { useCallback, useRef, useState } from "react";
import { Form } from "antd";
import { useTranslation } from "react-i18next";
import { agentsApi } from "@/api/modules/agents";
import { invalidateSkillCache, skillApi } from "@/api/modules/skill";
import { useAppMessage } from "@/hooks/useAppMessage";
import type {
  AgentProfileConfig,
  AgentSummary,
  CopyAgentRequest,
  CreateAgentRequest,
} from "@/api/types/agents";
import { MAIL_DOMAIN_WHITELIST } from "@/pages/Settings/Agents/components/mailDomains";

type ModelSettingsDraft = Pick<
  AgentProfileConfig,
  "fallback_models" | "fallback_policy" | "subagent_model"
>;

const EMPTY_MODEL_SETTINGS: ModelSettingsDraft = {
  fallback_models: [],
  fallback_policy: { enabled: true, target_scope: "configured" },
  subagent_model: null,
};

/**
 * 仅服务于表单交互的键（模型拆分选择 + 邮箱三字段）：
 * 后端契约里没有它们，提交前必须整体剔除。
 */
const FORM_ONLY_KEYS = [
  "active_model_provider",
  "active_model_model",
  "mail_mode",
  "mail_credential",
  "mail_push",
] as const;

export interface AgentFormModalOptions {
  /** 编辑保存成功后回调（刷新列表）。 */
  onUpdated: () => Promise<void> | void;
  /** 新建成功后回调（控制台直接进新员工工作台）。 */
  onCreated: (agentId: string) => void;
  /** 复制成功后回调。 */
  onCopied: (agentId: string) => Promise<void> | void;
}

export function useAgentFormModal(options: AgentFormModalOptions) {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const [form] = Form.useForm();
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentSummary | null>(null);
  const [copyModalVisible, setCopyModalVisible] = useState(false);
  const [copyingAgent, setCopyingAgent] = useState<AgentSummary | null>(null);
  const [copying, setCopying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [modelSettings, setModelSettings] =
    useState<ModelSettingsDraft>(EMPTY_MODEL_SETTINGS);
  const [modelSettingsResetToken, setModelSettingsResetToken] = useState(0);
  const installedSkillsRef = useRef<string[]>([]);

  const handleCreate = useCallback(() => {
    setEditingAgent(null);
    setModelSettings(EMPTY_MODEL_SETTINGS);
    setModelSettingsResetToken((token) => token + 1);
    form.resetFields();
    form.setFieldsValue({
      workspace_dir: "",
      active_model_provider: undefined,
      active_model_model: undefined,
      mail_mode: "none",
      mail_credential: undefined,
      mail_push: undefined,
      backend: "qwenpaw",
    });
    setSelectedSkills([]);
    installedSkillsRef.current = [];
    setModalVisible(true);
  }, [form]);

  const handleEdit = useCallback(
    async (agent: AgentSummary) => {
      try {
        setSelectedSkills([]);
        installedSkillsRef.current = [];
        invalidateSkillCache({ agentId: agent.id });
        const config = await agentsApi.getAgent(agent.id);
        setEditingAgent(agent);
        const { mail, ...configRest } = config;
        form.setFieldsValue({
          ...configRest,
          active_model_provider: config.active_model?.provider_id || undefined,
          active_model_model: config.active_model?.model || undefined,
          mail_mode: mail
            ? mail.is_new_account
              ? "dedicated"
              : "personal"
            : "none",
          mail_credential: mail ? mail.credential : undefined,
          mail_push: mail?.push
            ? {
                mode: mail.push.mode ?? "off",
                // 历史字段 subject 以 content 展示并保存（主题 + 正文双匹配）
                rules: (mail.push.rules ?? []).map((rule) =>
                  rule.field === "subject"
                    ? { ...rule, field: "content" as const }
                    : rule,
                ),
                poll_interval_seconds: mail.push.poll_interval_seconds,
                // 旧配置缺省时后端按 false 处理
                access_control_enabled: mail.push.access_control_enabled ?? false,
              }
            : undefined,
        });
        setModalVisible(true);
      } catch (error) {
        console.error("Failed to load agent config:", error);
        message.error(t("agent.loadConfigFailed"));
      }
    },
    [form, message, t],
  );

  const handleOpenCopy = useCallback((agent: AgentSummary) => {
    setCopyingAgent(agent);
    setCopyModalVisible(true);
  }, []);

  const handleCopy = useCallback(
    async (body: CopyAgentRequest) => {
      if (!copyingAgent) {
        return;
      }
      setCopying(true);
      try {
        const result = await agentsApi.copyAgent(copyingAgent.id, body);
        message.success(`${t("agent.copySuccess")} (ID: ${result.id})`);
        setCopyModalVisible(false);
        setCopyingAgent(null);
        await options.onCopied(result.id);
      } catch (error: unknown) {
        console.error("Failed to copy agent:", error);
        message.error(
          error instanceof Error ? error.message : t("agent.copyFailed"),
        );
      } finally {
        setCopying(false);
      }
    },
    [copyingAgent, message, options, t],
  );

  const handleInstalledSkillsLoaded = useCallback((skills: string[]) => {
    installedSkillsRef.current = skills;
  }, []);

  /** 组装邮箱推送配置（规则编辑器已隐藏，存量规则需原样透传）。 */
  const buildMailPayload = useCallback(
    (values: Record<string, unknown>) => {
      const mailMode = values.mail_mode as string | undefined;
      const credential = values.mail_credential as
        | { name?: string; domain?: string; provider?: string; auth_code?: string }
        | undefined;
      const mailPush = values.mail_push as
        | {
            mode?: string;
            rules?: Array<Record<string, unknown>>;
            poll_interval_seconds?: number;
            access_control_enabled?: boolean;
          }
        | undefined;
      // 规则编辑器不在表单里，需从 store 直接取，避免编辑旧员工时清空规则
      const storedMailPush = form.getFieldValue("mail_push") as
        | typeof mailPush
        | undefined;
      const pushMode = mailPush?.mode ?? storedMailPush?.mode ?? "off";
      const pushRules = (
        mailPush?.rules ?? storedMailPush?.rules ?? []
      ).map((rule) => ({
        field: rule?.field === "subject" ? "content" : rule?.field || "from",
        contains: String(rule?.contains ?? "").trim(),
        action: rule?.action || "notify",
        param: String(rule?.param ?? "").trim(),
      }));
      const push =
        pushMode === "off" && pushRules.length === 0
          ? null
          : {
              mode: pushMode,
              rules: pushRules,
              ...(mailPush?.poll_interval_seconds ??
              storedMailPush?.poll_interval_seconds
                ? {
                    poll_interval_seconds:
                      mailPush?.poll_interval_seconds ??
                      storedMailPush?.poll_interval_seconds,
                  }
                : {}),
              // 访问控制是 opt-in，缺省即关闭，必须显式提交
              access_control_enabled: Boolean(
                mailPush?.access_control_enabled ??
                  storedMailPush?.access_control_enabled ??
                  false,
              ),
            };
      // 邮箱仅支持 qwenpaw 后端，第三方后端绝不提交 mail 配置（后端会拒绝）
      if (values.backend !== "qwenpaw" || (mailMode !== "personal" && mailMode !== "dedicated")) {
        return null;
      }
      const domain = credential?.domain || "163.com";
      return {
        is_new_account: mailMode === "dedicated",
        credential: {
          name: (credential?.name ?? "").trim(),
          domain,
          // 白名单域固定空 provider，自建企业域才带所选 provider
          provider: MAIL_DOMAIN_WHITELIST.includes(domain)
            ? ""
            : credential?.provider || "",
          auth_code: credential?.auth_code || "",
        },
        ...(push ? { push } : {}),
      };
    },
    [form],
  );

  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const workspaceRaw = values.workspace_dir;
      const workspace_dir =
        typeof workspaceRaw === "string"
          ? workspaceRaw.trim() || undefined
          : workspaceRaw;
      const providerId = values.active_model_provider;
      const modelId = values.active_model_model;
      const active_model =
        values.backend === "qwenpaw" && providerId && modelId
          ? { provider_id: providerId, model: modelId }
          : null;
      const rest: Record<string, unknown> = Object.fromEntries(
        Object.entries(values).filter(
          ([key]) =>
            !FORM_ONLY_KEYS.includes(key as (typeof FORM_ONLY_KEYS)[number]),
        ),
      );
      // antd validateFields 的返回形状由表单注册项决定（无静态类型），
      // 剔除表单专用键后在调用点按后端契约类型提交
      const payload: Record<string, unknown> = {
        ...rest,
        workspace_dir,
        active_model,
        mail: buildMailPayload(values),
      };
      setSaving(true);

      if (editingAgent) {
        const previousInstalledSkills = installedSkillsRef.current;
        const newSkills =
          values.backend === "qwenpaw"
            ? selectedSkills.filter(
                (skill) => !previousInstalledSkills.includes(skill),
              )
            : [];
        for (const skill of newSkills) {
          await skillApi.downloadSkillPoolSkill({
            skill_name: skill,
            targets: [{ workspace_id: editingAgent.id }],
          });
        }
        await agentsApi.updateAgent(
          editingAgent.id,
          payload as unknown as AgentProfileConfig,
        );
        installedSkillsRef.current = [
          ...previousInstalledSkills,
          ...newSkills.filter(
            (skill) => !previousInstalledSkills.includes(skill),
          ),
        ];
        invalidateSkillCache({ agentId: editingAgent.id });
        message.success(t("agent.updateSuccess"));
        setModalVisible(false);
        await options.onUpdated();
      } else {
        const result = await agentsApi.createAgent({
          ...(payload as unknown as CreateAgentRequest),
          ...(values.backend === "qwenpaw" ? modelSettings : {}),
          language: i18n.language,
          skill_names: values.backend === "qwenpaw" ? selectedSkills : [],
        });
        message.success(`${t("agent.createSuccess")} (ID: ${result.id})`);
        setModalVisible(false);
        await options.onUpdated();
        options.onCreated(result.id);
      }
    } catch (error: unknown) {
      if (editingAgent) {
        invalidateSkillCache({ agentId: editingAgent.id });
      }
      console.error("Failed to save agent:", error);
      const text = error instanceof Error ? error.message : "";
      message.error(text || t("agent.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [
    buildMailPayload,
    editingAgent,
    form,
    i18n.language,
    message,
    modelSettings,
    options,
    selectedSkills,
    t,
  ]);

  return {
    form,
    modalVisible,
    editingAgent,
    selectedSkills,
    setSelectedSkills,
    modelSettings: editingAgent ? undefined : modelSettings,
    modelSettingsResetToken,
    onModelSettingsChange: setModelSettings,
    onInstalledSkillsLoaded: handleInstalledSkillsLoaded,
    openCreate: handleCreate,
    openEdit: handleEdit,
    closeModal: () => setModalVisible(false),
    submit: handleSubmit,
    saving,
    copyModalVisible,
    copyingAgent,
    copying,
    openCopy: handleOpenCopy,
    copy: handleCopy,
    closeCopyModal: () => {
      setCopyModalVisible(false);
      setCopyingAgent(null);
    },
  };
}
