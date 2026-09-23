/**
 * ExpertAvatarPicker.tsx — 数字员工形象选择器（管理端编辑表单）。
 *
 * 作为 antd Form 受控组件（value/onChange 约定），value 即
 * experts.icon 原始值：dicebear://<style>/<seed>；"恢复自动"写回
 * 空串（展示层按 expertId 自动分配）。风格切换保留原 seed，"换一个"
 * 重掷随机 seed。
 */
import { ReloadOutlined } from "@ant-design/icons";
import { Button, Select, Space } from "antd";
import { useTranslation } from "react-i18next";
import ExpertAvatar from "@/components/ExpertAvatar";
import {
  buildExpertIcon,
  EXPERT_AVATAR_STYLES,
  resolveExpertAvatar,
  type ExpertAvatarStyle,
} from "@/utils/expertAvatar";

/** 各风格的展示名（风格名保持官方拼写便于对照 dicebear.com/styles）。 */
const STYLE_LABELS: Record<ExpertAvatarStyle, string> = {
  lorelei: "Lorelei",
  adventurer: "Adventurer",
  personas: "Personas",
  notionists: "Notionists",
  avataaars: "Avataaars",
  "big-smile": "Big Smile",
};

interface ExpertAvatarPickerProps {
  value?: string;
  onChange?: (value: string) => void;
  /** 编辑已有专家时的稳定 ID（自动分配预览用）；新建为空。 */
  expertId?: string;
  name?: string;
}

export default function ExpertAvatarPicker({
  value,
  onChange,
  expertId,
  name,
}: ExpertAvatarPickerProps) {
  const { t } = useTranslation();
  const previewId = expertId || "draft-preview";
  const resolved = resolveExpertAvatar(value, previewId);

  const keepStyle = resolved?.style ?? EXPERT_AVATAR_STYLES[0];

  return (
    <Space size="middle" align="center" wrap>
      <ExpertAvatar
        icon={value}
        expertId={previewId}
        name={name}
        size={56}
        style={{ border: "0.5px solid var(--sd-line, #e5e7eb)" }}
      />
      <Select
        style={{ width: 160 }}
        placeholder={t("admin.experts.avatarStyle", "形象风格")}
        value={resolved?.style}
        onChange={(style: ExpertAvatarStyle) =>
          onChange?.(buildExpertIcon(style, resolved?.seed || previewId))
        }
        options={EXPERT_AVATAR_STYLES.map((style) => ({
          value: style,
          label: STYLE_LABELS[style],
        }))}
      />
      <Button
        icon={<ReloadOutlined />}
        onClick={() =>
          onChange?.(
            buildExpertIcon(
              keepStyle,
              `seed-${Math.random().toString(36).slice(2, 10)}`,
            ),
          )
        }
      >
        {t("admin.experts.avatarShuffle", "换一个")}
      </Button>
      <Button onClick={() => onChange?.("")}>
        {t("admin.experts.avatarAuto", "恢复自动")}
      </Button>
    </Space>
  );
}
