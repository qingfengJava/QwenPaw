/**
 * mentionChipView.tsx — 聊天消息气泡内 @ 引用 / 技能斜杠的内联胶囊渲染。
 *
 * 输入框侧的 mention chip 由 mentionChipOverlay（镜像层）渲染，但消息
 * 发送后落库的是协议纯文本（`@ 档案名` / 句首 `/技能名`），SDK 用户气泡
 * 以 raw 纯文本渲染，历史消息里胶囊退化为裸文字。本模块复用镜像层同一
 * 套 token 切分（buildChipSegments）与分类（classifyMentionToken），把
 * 用户消息文本渲染为与输入框一致的胶囊（图标 + 名称），未命中 token 的
 * 文本原样保留，协议文本本身不做任何改写。
 *
 * 挂载方式：Chat 页 options.cards 覆盖 SDK 的 Text 卡 —— 仅当卡片数据
 * 是 raw 纯文本（即用户消息；助手消息走 Markdown 分支）时启用胶囊渲染，
 * 其余情况原样委托 SDK 默认 Text 卡（DefaultCards.Text），助手回复的
 * Markdown 渲染、typing 光标等行为完全不受影响。
 *
 * @author qingfeng
 */

import { FileTextOutlined, ThunderboltOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";
import { DefaultCards, useProviderContext } from "@agentscope-ai/chat";
import { buildChipSegments } from "./mentionChipOverlay";
import { classifyMentionToken } from "./mentionCatalog";
import styles from "./index.module.less";

/** 胶囊展示名：去掉 `@ `/`/` 协议前缀（与输入框胶囊同款不含 @）。 */
function chipDisplayName(token: string): string {
  return token.replace(/^@\s?/, "").replace(/^\//, "");
}

/**
 * 把消息文本切分为 普通文本/胶囊 段并渲染为 ReactNode 列表。
 *
 * 切分复用输入框镜像层的 buildChipSegments：顺序拼接后与原文一致；
 * 无 token 时返回单个文本节点，行为等价于 SDK Raw 的直出渲染。
 */
function renderMentionChipNodes(text: string): ReactNode[] {
  return buildChipSegments(text).map((segment, index) => {
    if (segment.kind === "text") {
      return segment.value;
    }
    const kind = classifyMentionToken(segment.value);
    const icon =
      kind === "skill" ? (
        <ThunderboltOutlined className={styles.mentionChipIcon} />
      ) : (
        <FileTextOutlined className={styles.mentionChipIcon} />
      );
    return (
      <span
        key={index}
        className={styles.mentionChip}
        data-chip-kind={kind}
        title={segment.value.trim()}
      >
        {icon}
        <span className={styles.mentionChipName}>
          {chipDisplayName(segment.value)}
        </span>
      </span>
    );
  });
}

/** SDK Text 卡的数据形态（raw 用户消息为纯文本；助手消息走 Markdown）。 */
interface TextCardData {
  content?: unknown;
  raw?: boolean;

  [key: string]: unknown;
}

interface TextCardProps {
  data?: TextCardData;

  [key: string]: unknown;
}

/**
 * 消息气泡 Text 卡：raw 纯文本（用户消息）启用 mention 胶囊渲染，
 * 其余数据形态委托 SDK 默认 Text 卡（Markdown 渲染）。
 *
 * 容器复用 SDK Markdown 的 prefixCls，与 Raw 分支同构（裸 div + 文本），
 * 保证字号、行高、换行等样式与默认渲染逐像素一致。
 *
 * @author qingfeng
 */
export function MentionAwareTextCard(props: TextCardProps) {
  const data = props?.data;
  const prefixCls = useProviderContext().getPrefixCls("markdown");

  if (data && data.raw === true && typeof data.content === "string") {
    return <div className={prefixCls}>{renderMentionChipNodes(data.content)}</div>;
  }
  return <DefaultCards.Text {...props} />;
}
