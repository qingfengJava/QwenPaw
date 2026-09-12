import { useCallback, useEffect, useMemo, useState, type Key } from "react";
import {
  Button,
  Drawer,
  Empty,
  Input,
  Select,
  Switch,
  Tag,
  Tooltip,
} from "@agentscope-ai/design";
import { Spin, Tabs, Tree } from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileOutlined,
  FolderOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { XMarkdown } from "@ant-design/x-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import type { DataNode } from "antd/es/tree";
import type {
  PoolSkillDetail,
  PoolSkillSpec,
  SkillAutomationUpdate,
  SkillFileContent,
  SkillFileNode,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { MAX_TAGS, MAX_TAG_LENGTH } from "../../../Agent/Skills/components";
import { skillApi } from "../../../../api/modules/skill";
import {
  deriveInstalledFromLabel,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { hardenSingleBreaks, stripFrontmatter } from "../../../../utils/markdown";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import { renderableCodeComponents } from "../../../../components/RenderableCodeBlock";
import { useTheme } from "../../../../contexts/ThemeContext";
import { SkillVisual } from "@/components/SkillVisual";
import styles from "../index.module.less";

interface PoolSkillDetailDrawerProps {
  open: boolean;
  skill: PoolSkillDetail | null;
  loading?: boolean;
  workspaces: WorkspaceSkillSummary[];
  // 内嵌编辑态：Hero 按钮切换保存/取消，SKILL.md 在右侧宽区域直接编辑
  editing?: boolean;
  editContent?: string;
  saving?: boolean;
  onStartEdit?: () => void;
  onCancelEdit?: () => void;
  onEditContentChange?: (content: string) => void;
  onSaveEdit?: () => void;
  // 设置 Tab：治理字段分项保存（对齐旧编辑抽屉的字段面）
  availableTags?: string[];
  onRenameSettings?: (newName: string) => void | Promise<void>;
  onSaveSettingsTags?: (tags: string[]) => void | Promise<void>;
  onSaveSettingsI18n?: (payload: {
    display_name_zh: string;
    description_zh: string;
  }) => void | Promise<void>;
  onSaveSettingsAutomation?: (
    update: SkillAutomationUpdate,
  ) => void | Promise<void>;
  onSaveSettingsConfig?: (configText: string) => void | Promise<void>;
  onClose: () => void;
  onBroadcast: (skill: PoolSkillSpec) => void;
  onDelete: (skill: PoolSkillSpec) => void;
}

// 默认打开的主文件（技能说明）
const ENTRY_FILE = "SKILL.md";
// 元信息条日期展示格式（对齐竞品 2026.08.25 风格）
const META_DATE_FORMAT = "YYYY.MM.DD";

function toTreeData(nodes: SkillFileNode[]): DataNode[] {
  return nodes.map((node) => ({
    title: node.name,
    key: node.path,
    isLeaf: node.type !== "dir",
    icon:
      node.type === "dir" ? (
        <FolderOutlined />
      ) : (
        <FileOutlined />
      ),
    children:
      node.children && node.children.length > 0
        ? toTreeData(node.children)
        : undefined,
  }));
}

function findDefaultSelection(
  nodes: SkillFileNode[],
): string {
  // 优先选中 SKILL.md 主文件；否则选第一个文件节点
  for (const node of nodes) {
    if (node.type === "file" && node.path === ENTRY_FILE) {
      return node.path;
    }
  }
  for (const node of nodes) {
    if (node.type === "file") {
      return node.path;
    }
  }
  return "";
}

function collectFileNodes(nodes: SkillFileNode[]): SkillFileNode[] {
  // 递归平铺整棵树（目录可能任意嵌套）
  return nodes.flatMap((node) =>
    node.children && node.children.length > 0
      ? [node, ...collectFileNodes(node.children)]
      : [node],
  );
}

function isMarkdownPath(path: string): boolean {
  return path.toLowerCase().endsWith(".md");
}

function downloadSkillFile(file: SkillFileContent): void {
  const anchor = document.createElement("a");
  if (file.type === "image" && file.data_url) {
    anchor.href = file.data_url;
  } else {
    const blob = new Blob([file.content || ""], {
      type: "text/plain;charset=utf-8",
    });
    anchor.href = URL.createObjectURL(blob);
  }
  anchor.download = file.name || "file";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (file.type !== "image") {
    window.setTimeout(() => URL.revokeObjectURL(anchor.href), 0);
  }
}

export function PoolSkillDetailDrawer({
  open,
  skill,
  loading = false,
  workspaces,
  editing = false,
  editContent = "",
  saving = false,
  onStartEdit,
  onCancelEdit,
  onEditContentChange,
  onSaveEdit,
  availableTags = [],
  onRenameSettings,
  onSaveSettingsTags,
  onSaveSettingsI18n,
  onSaveSettingsAutomation,
  onSaveSettingsConfig,
  onClose,
  onBroadcast,
  onDelete,
}: PoolSkillDetailDrawerProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [files, setFiles] = useState<SkillFileNode[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [selectedPath, setSelectedPath] = useState("");
  const [contentCache, setContentCache] = useState<
    Record<string, SkillFileContent>
  >({});
  const [contentLoading, setContentLoading] = useState(false);
  // 编辑态下 MarkdownCopy 的预览/源码切换（初始源码模式）
  const [editShowPreview, setEditShowPreview] = useState(false);
  // 设置 Tab：治理字段本地暂存（activeSkill 变化时重置）
  const [settingsName, setSettingsName] = useState("");
  const [settingsTags, setSettingsTags] = useState<string[]>([]);
  const [settingsI18nName, setSettingsI18nName] = useState("");
  const [settingsI18nDesc, setSettingsI18nDesc] = useState("");
  const [settingsAutoUpdate, setSettingsAutoUpdate] = useState(false);
  const [settingsAutoSync, setSettingsAutoSync] = useState(false);
  const [settingsAutoSyncTargets, setSettingsAutoSyncTargets] = useState<
    string[]
  >([]);
  const [settingsConfigText, setSettingsConfigText] = useState("{}");
  const [activeTab, setActiveTab] = useState("files");

  const skillName = skill?.name || "";

  // 打开/切换技能时重置设置 Tab 的本地暂存值
  useEffect(() => {
    if (!open || !skill) return;
    setSettingsName(skill.name);
    setSettingsTags(skill.tags || []);
    setSettingsI18nName(skill.display_name_zh || "");
    setSettingsI18nDesc(skill.description_zh || "");
    setSettingsAutoUpdate(Boolean(skill.auto_update));
    setSettingsAutoSync(Boolean(skill.auto_sync));
    setSettingsAutoSyncTargets(skill.auto_sync_targets ?? []);
    setSettingsConfigText(JSON.stringify(skill.config || {}, null, 2));
    setActiveTab("files");
  }, [open, skill]);

  useEffect(() => {
    if (!open || !skillName) {
      setFiles([]);
      setSelectedPath("");
      setContentCache({});
      return;
    }
    let cancelled = false;
    setFilesLoading(true);
    void skillApi
      .listPoolSkillFiles(skillName)
      .then((tree) => {
        if (cancelled) return;
        setFiles(tree || []);
        setSelectedPath(findDefaultSelection(tree || []));
      })
      .finally(() => {
        if (!cancelled) setFilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, skillName]);

  useEffect(() => {
    if (!open || !skillName || !selectedPath) return;
    if (contentCache[selectedPath]) return;
    let cancelled = false;
    setContentLoading(true);
    void skillApi
      .getPoolSkillFile(skillName, selectedPath)
      .then((file) => {
        if (cancelled) return;
        setContentCache((prev) => ({ ...prev, [selectedPath]: file }));
      })
      .finally(() => {
        if (!cancelled) setContentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, skillName, selectedPath, contentCache]);

  const treeData = useMemo(() => toTreeData(files), [files]);

  const activeFile = selectedPath ? contentCache[selectedPath] : undefined;
  const isMarkdown = isMarkdownPath(selectedPath);

  const usedByNames = useMemo(() => {
    const nameById = new Map(
      workspaces.map((ws) => [ws.agent_id, ws.agent_name || ""]),
    );
    return (skill?.used_by || []).map((agentId) =>
      getAgentDisplayName(
        { id: agentId, name: nameById.get(agentId) || "" },
        t,
      ),
    );
  }, [skill?.used_by, workspaces, t]);

  const metaItems = useMemo(() => {
    const languageValue = isSkillBuiltin(skill?.source)
      ? (skill?.builtin_language || "").toLowerCase() === "zh"
        ? t("skillPool.langZh")
        : (skill?.builtin_language || "").toLowerCase() === "en"
        ? t("skillPool.langEn")
        : "-"
      : "-";
    return [
      {
        label: t("skillPool.detailSource"),
        value: skill?.external
          ? skill?.external_path || t("skillPool.sourceExternal")
          : deriveInstalledFromLabel(skill?.installed_from || "") || "-",
      },
      { label: t("skillPool.detailVersion"), value: skill?.version || "-" },
      {
        label: t("skillPool.detailUpdatedAt"),
        value: skill?.last_updated
          ? dayjs(skill.last_updated).format(META_DATE_FORMAT)
          : "-",
      },
      { label: t("skillPool.detailLanguage"), value: languageValue },
      {
        label: t("skillPool.detailUsedBy"),
        value: String(skill?.used_by?.length ?? 0),
        hint: usedByNames.join("、"),
      },
    ];
  }, [skill, usedByNames, t]);

  const handleDownload = useCallback(() => {
    if (activeFile) downloadSkillFile(activeFile);
  }, [activeFile]);

  // 设置 Tab：各治理字段分节渲染（对齐旧编辑抽屉的字段面）
  const renderSettingsPanel = () => {
    if (!skill) return null;
    const builtin = isSkillBuiltin(skill.source);
    return (
      <div className={styles.detailSettingsPanel}>
        {/* 左列：身份与展示字段（改名 / 标签 / 中文映射） */}
        <div className={styles.detailSettingsColumn}>
          {/* 改名 */}
          <section className={styles.detailSettingsSection}>
            <div className={styles.detailSettingsTitle}>
              {t("skillPool.skillName")}
            </div>
            <div className={styles.detailSettingsRow}>
              <Input
                value={settingsName}
                onChange={(e) => setSettingsName(e.target.value)}
              />
              <Button
                disabled={settingsName.trim() === skill.name}
                onClick={() => void onRenameSettings?.(settingsName)}
              >
                {t("common.save")}
              </Button>
            </div>
          </section>

          {/* 标签 */}
          <section className={styles.detailSettingsSection}>
            <div className={styles.detailSettingsTitle}>
              {t("skillPool.tags")}
            </div>
            <div className={styles.detailSettingsRow}>
              <Select
                mode="tags"
                style={{ width: "100%" }}
                value={settingsTags}
                onChange={setSettingsTags}
                options={availableTags.map((tag) => ({
                  label: tag,
                  value: tag,
                }))}
                placeholder={t("skillPool.tagsPlaceholder")}
                maxCount={MAX_TAGS}
              />
              <Button
                disabled={
                  settingsTags.some((v) => v.length > MAX_TAG_LENGTH) ||
                  JSON.stringify(settingsTags) === JSON.stringify(skill.tags || [])
                }
                onClick={() => void onSaveSettingsTags?.(settingsTags)}
              >
                {t("common.save")}
              </Button>
            </div>
          </section>

          {/* 中文映射 */}
          <section className={styles.detailSettingsSection}>
            <div className={styles.detailSettingsTitle}>
              {t("skillPool.i18nSection")}
            </div>
            <div className={styles.detailSettingsStack}>
              <Input
                value={settingsI18nName}
                placeholder={t("skillPool.i18nNameLabel")}
                onChange={(e) => setSettingsI18nName(e.target.value)}
              />
              <Input.TextArea
                rows={2}
                value={settingsI18nDesc}
                placeholder={t("skillPool.i18nDescLabel")}
                onChange={(e) => setSettingsI18nDesc(e.target.value)}
              />
              <Button
                disabled={
                  settingsI18nName === (skill.display_name_zh || "") &&
                  settingsI18nDesc === (skill.description_zh || "")
                }
                onClick={() =>
                  void onSaveSettingsI18n?.({
                    display_name_zh: settingsI18nName,
                    description_zh: settingsI18nDesc,
                  })
                }
              >
                {t("skillPool.i18nSave")}
              </Button>
            </div>
          </section>
        </div>

        {/* 右列：运行行为字段（自动化 / config） */}
        <div className={styles.detailSettingsColumn}>
          {/* 自动化：开关即改 */}
          <section className={styles.detailSettingsSection}>
            <div className={styles.detailSettingsTitle}>
              {t("skillPool.automation")}
            </div>
            <div className={styles.detailSettingsStack}>
              {builtin && (
                <div className={styles.detailSettingsRow}>
                  <div>
                    <div>{t("skillPool.builtinAutoUpdate")}</div>
                    <div className={styles.detailSettingsHint}>
                      {t("skillPool.builtinAutoUpdateFlow")}
                    </div>
                  </div>
                  <Switch
                    checked={settingsAutoUpdate}
                    onChange={(checked) => {
                      setSettingsAutoUpdate(checked);
                      void onSaveSettingsAutomation?.({ auto_update: checked });
                    }}
                  />
                </div>
              )}
              <div className={styles.detailSettingsRow}>
                <div>
                  <div>{t("skillPool.autoSync")}</div>
                  <div className={styles.detailSettingsHint}>
                    {t("skillPool.autoSyncFlow")}
                  </div>
                </div>
                <Switch
                  checked={settingsAutoSync}
                  onChange={(checked) => {
                    setSettingsAutoSync(checked);
                    void onSaveSettingsAutomation?.({
                      auto_sync: {
                        enabled: checked,
                        targets: checked ? settingsAutoSyncTargets : null,
                      },
                    });
                  }}
                />
              </div>
              {settingsAutoSync && (
                <Select
                  mode="multiple"
                  style={{ width: "100%" }}
                  value={settingsAutoSyncTargets.filter((id) =>
                    workspaces.some((ws) => ws.agent_id === id),
                  )}
                  onChange={(value) => {
                    const targets = value as string[];
                    setSettingsAutoSyncTargets(targets);
                    void onSaveSettingsAutomation?.({
                      auto_sync: { enabled: true, targets },
                    });
                  }}
                  placeholder={t("skillPool.autoSyncAgentsPlaceholder")}
                  options={workspaces.map((ws) => ({
                    label: getAgentDisplayName(
                      { id: ws.agent_id, name: ws.agent_name ?? "" },
                      t,
                    ),
                    value: ws.agent_id,
                  }))}
                />
              )}
            </div>
          </section>

          {/* config */}
          <section className={styles.detailSettingsSection}>
            <div className={styles.detailSettingsTitle}>
              {t("skills.config")}
            </div>
            <div className={styles.detailSettingsStack}>
              <Input.TextArea
                rows={6}
                value={settingsConfigText}
                onChange={(e) => setSettingsConfigText(e.target.value)}
                placeholder={t("skills.configPlaceholder")}
              />
              <Button
                disabled={
                  settingsConfigText === JSON.stringify(skill.config || {}, null, 2)
                }
                onClick={() => void onSaveSettingsConfig?.(settingsConfigText)}
              >
                {t("common.save")}
              </Button>
            </div>
          </section>
        </div>
      </div>
    );
  };

  const renderViewerBody = () => {
    // 编辑态 + Markdown 文件：右侧宽区域直接编辑（预览/源码可切换）
    if (editing && isMarkdown) {
      return (
        <div className={styles.detailMarkdownEdit}>
          <MarkdownCopy
            content={editContent}
            showMarkdown={editShowPreview}
            onShowMarkdownChange={setEditShowPreview}
            editable={true}
            onContentChange={(value) => onEditContentChange?.(value)}
            textareaProps={{
              rows: 24,
              placeholder: t("skillPool.contentPlaceholder"),
            }}
          />
        </div>
      );
    }
    if (contentLoading) {
      return (
        <div className={styles.detailViewerLoading}>
          <Spin />
        </div>
      );
    }
    if (!activeFile) {
      return (
        <div className={styles.detailViewerLoading}>
          <Empty />
        </div>
      );
    }
    if (activeFile.type === "image" && activeFile.data_url) {
      return (
        <div className={styles.detailImageView}>
          <img alt={activeFile.name} src={activeFile.data_url} />
        </div>
      );
    }
    if (activeFile.type === "binary") {
      return (
        <div className={styles.detailBinaryView}>
          <Empty
            description={t("skillPool.detailBinaryHint", {
              size: activeFile.size ?? 0,
            })}
          >
            <Button icon={<DownloadOutlined />} onClick={handleDownload}>
              {t("skillPool.detailDownload")}
            </Button>
          </Empty>
        </div>
      );
    }
    // Markdown 主文件走富文本渲染，其余文本走代码高亮
    if (isMarkdown) {
      return (
        <div className={styles.detailMarkdownView}>
          <XMarkdown
            content={hardenSingleBreaks(
              stripFrontmatter(activeFile.content || ""),
            )}
            components={renderableCodeComponents}
            dompurifyConfig={{
              ADD_TAGS: ["pre", "code"],
              ADD_ATTR: ["data-block", "data-state", "data-lang", "class"],
            }}
          />
        </div>
      );
    }
    return (
      <div className={styles.detailCodeView}>
        <SyntaxHighlighter
          codeTagProps={{ style: { background: "transparent" } }}
          customStyle={{
            background: "transparent",
            fontSize: "13px",
            lineHeight: "1.65",
            margin: 0,
            padding: "16px 20px",
          }}
          language={activeFile.language || "text"}
          style={isDark ? oneDark : oneLight}
          wrapLongLines
        >
          {activeFile.content || ""}
        </SyntaxHighlighter>
      </div>
    );
  };

  return (
    <Drawer
      width="62%"
      placement="right"
      open={open}
      onClose={onClose}
      destroyOnHidden
      title={t("skillPool.detailTitle")}
      styles={{
        body: { padding: 0, display: "flex", flexDirection: "column" },
        // 超宽屏限宽，避免百分比宽度下抽屉过宽、内容两侧留白失衡
        wrapper: { maxWidth: 1440 },
      }}
    >
      {loading || !skill ? (
        <div className={styles.detailViewerLoading}>
          <Spin />
        </div>
      ) : (
        <>
          {/* Hero 区：图标 + 名称 + 标签 + 描述 + 操作 */}
          <div className={styles.detailHero}>
            <span className={styles.detailHeroIcon}>
              <SkillVisual name={skill.name} emoji={skill.emoji} />
            </span>
            <div className={styles.detailHeroInfo}>
              <div className={styles.detailHeroTitleRow}>
                <span className={styles.detailHeroName}>
                  {skill.display_name_zh || skill.name}
                </span>
                {skill.display_name_zh && (
                  <span className={styles.detailHeroSub}>{skill.name}</span>
                )}
                {isSkillBuiltin(skill.source) ? (
                  <Tag>{t("skillPool.builtin")}</Tag>
                ) : (
                  <Tag color="blue">{t("skillPool.custom")}</Tag>
                )}
                {skill.missing && (
                  <Tag color="warning">{t("skillPool.missingContent")}</Tag>
                )}
                <span
                  className={`${styles.detailStatusBadge} ${
                    styles[getPoolBuiltinStatusTone(skill.sync_status)] || ""
                  }`}
                >
                  {getPoolBuiltinStatusLabel(skill.sync_status, t)}
                </span>
              </div>
              <p className={styles.detailHeroDesc}>
                {skill.description_zh || skill.description || "-"}
              </p>
            </div>
            <div className={styles.detailHeroActions}>
              {editing ? (
                <>
                  <Button onClick={onCancelEdit} disabled={saving}>
                    {t("common.cancel")}
                  </Button>
                  <Button
                    data-testid="skill-detail-save-btn"
                    type="primary"
                    loading={saving}
                    onClick={onSaveEdit}
                  >
                    {t("common.save")}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    data-testid="skill-detail-broadcast-btn"
                    icon={<SendOutlined />}
                    onClick={() => onBroadcast(skill)}
                  >
                    {t("skillPool.broadcast")}
                  </Button>
                  <Button
                    danger
                    data-testid="skill-detail-delete-btn"
                    icon={<DeleteOutlined />}
                    onClick={() => onDelete(skill)}
                  >
                    {t("skillPool.delete")}
                  </Button>
                  <Button
                    data-testid="skill-detail-edit-btn"
                    type="primary"
                    icon={<EditOutlined />}
                    onClick={() => onStartEdit?.()}
                  >
                    {t("common.edit")}
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* 元信息条：来源 / 版本 / 更新时间 / 语言 / 装配员工数 */}
          <div className={styles.detailMetaBar}>
            {metaItems.map((item, index) => {
              const inner = (
                <span className={styles.detailMetaInner}>
                  <span className={styles.detailMetaValue}>{item.value}</span>
                  <span className={styles.detailMetaLabel}>{item.label}</span>
                </span>
              );
              return (
                <div className={styles.detailMetaItem} key={item.label}>
                  {index > 0 && <span className={styles.detailMetaDivider} />}
                  {item.hint ? (
                    <Tooltip title={item.hint}>{inner}</Tooltip>
                  ) : (
                    inner
                  )}
                </div>
              );
            })}
          </div>

          {/* 主体：文件内容 / 设置 Tab */}
          <Tabs
            activeKey={activeTab}
            className={styles.detailTabs}
            items={[
              {
                key: "files",
                label: t("skillPool.detailTabFiles"),
                children: (
                  <div className={styles.detailBody}>
                    <div className={styles.detailTreePanel}>
                      {filesLoading ? (
                        <div className={styles.detailViewerLoading}>
                          <Spin />
                        </div>
                      ) : (
                        <Tree
                          blockNode
                          showIcon
                          defaultExpandAll
                          onSelect={(keys: Key[]) => {
                            const key = String(keys[0] || "");
                            // 目录节点仅做展开，不进入查看器
                            const node = collectFileNodes(files).find(
                              (item) => item.path === key,
                            );
                            if (key && (!node || node.type !== "dir")) {
                              setSelectedPath(key);
                            }
                          }}
                          selectedKeys={selectedPath ? [selectedPath] : []}
                          treeData={treeData}
                        />
                      )}
                    </div>
                    <div className={styles.detailViewerPanel}>
                      <div className={styles.detailViewerHeader}>
                        <span className={styles.detailViewerPath}>
                          {selectedPath || "-"}
                        </span>
                        {editing && isMarkdown ? (
                          <Tag color="processing">{t("skillPool.editingBadge")}</Tag>
                        ) : (
                          activeFile && (
                            <Button
                              icon={<DownloadOutlined />}
                              size="small"
                              onClick={handleDownload}
                            >
                              {t("skillPool.detailDownload")}
                            </Button>
                          )
                        )}
                      </div>
                      <div className={styles.detailViewerBody}>
                        {renderViewerBody()}
                      </div>
                    </div>
                  </div>
                ),
              },
              {
                key: "settings",
                label: t("skillPool.detailTabSettings"),
                children: renderSettingsPanel(),
              },
            ]}
            onChange={setActiveTab}
          />
        </>
      )}
    </Drawer>
  );
}
