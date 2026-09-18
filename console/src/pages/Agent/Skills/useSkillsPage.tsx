import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Form, Modal } from "@agentscope-ai/design";
import type { PoolSkillSpec, SkillDetail, SkillSpec } from "../../../api/types";
import type { SkillDrawerFormValues } from "./components";
import { useConflictRenameModal } from "./components";
import { useProgressiveRender } from "../../../hooks/useProgressiveRender";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../../stores/agentStore";
import { useAuthStore } from "../../../stores/authStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import { useUploadLimitStore } from "../../../stores/uploadLimitStore";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { SecurityScanErrorResponse } from "../../../api/modules/security";
import { parseErrorDetail } from "../../../utils/error";
import {
  checkScanWarnings as checkScanWarningsShared,
  showScanErrorModal,
} from "../../../utils/scanError";
import { useSkills } from "./useSkills";
import { useSkillFilter } from "./useSkillFilter";

// ─── Types ──────────────────────────────────────────────────────────────────

export type DownloadConflict =
  | { skill_name: string; reason: "conflict" }
  | {
      skill_name: string;
      reason: "builtin_upgrade";
      current_version_text: string;
      source_version_text: string;
    }
  | {
      skill_name: string;
      reason: "language_switch";
      source_language: string;
      current_language: string;
    };

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useSkillsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();

  // 当前登录用户（认证关闭时为空串）：驱动「共享/我的」资产分区；
  // 单机（无认证）恒为共享，不显示分区切换。
  const currentUsername = useAuthStore((s) => s.username);
  const scopeEnabled = Boolean(currentUsername);
  const [scopeFilter, setScopeFilter] = useState<"shared" | "mine">(
    "shared",
  );
  const isPersonalScope = scopeEnabled && scopeFilter === "mine";

  const {
    skills,
    providerSkills,
    loading,
    uploading,
    importing,
    createSkill,
    uploadSkill,
    importFromHub,
    cancelImport,
    toggleEnabled,
    deleteSkill,
    refreshSkills,
    hardRefresh,
  } = useSkills();

  // 分区过滤：后端 GET /skills 已按可见性返回（共享 + 当前用户的个人），
  // 这里按 source 二次分区，供「共享 / 我的」两个视图使用。
  const scopedSkills = useMemo(
    () =>
      isPersonalScope
        ? skills.filter((s) => s.source === "personal")
        : skills.filter((s) => s.source !== "personal"),
    [skills, isPersonalScope],
  );

  const {
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    allTags,
    filteredSkills,
  } = useSkillFilter(scopedSkills);

  const { showConflictRenameModal, conflictRenameModal } =
    useConflictRenameModal();

  // ── Local state ─────────────────────────────────────────────────────────

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillDetail | null>(null);
  const [editingSkillName, setEditingSkillName] = useState("");
  const [drawerLoading, setDrawerLoading] = useState(false);
  const detailRequestIdRef = useRef(0);
  const [form] = Form.useForm<SkillDrawerFormValues>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [poolModal, setPoolModal] = useState<"upload" | "download" | null>(
    null,
  );
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set());
  const [batchModeEnabled, setBatchModeEnabled] = useState(false);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [filterOpen, setFilterOpen] = useState(false);

  // ── Derived ─────────────────────────────────────────────────────────────

  const sortedSkills = useMemo(
    () =>
      filteredSkills.slice().sort((a, b) => {
        if (a.enabled && !b.enabled) return -1;
        if (!a.enabled && b.enabled) return 1;
        return a.name.localeCompare(b.name);
      }),
    [filteredSkills],
  );

  const {
    visibleItems: visibleSkills,
    hasMore,
    sentinelRef,
  } = useProgressiveRender(sortedSkills);

  // ── Effects ─────────────────────────────────────────────────────────────

  useEffect(() => {
    if (poolModal === "upload" || poolModal === "download") {
      void api
        .listSkillPoolSkills()
        .then(setPoolSkills)
        .catch(() => undefined);
    }
  }, [poolModal]);

  // ── Helpers ─────────────────────────────────────────────────────────────

  const confirmOverwrite = (title: string, content: ReactNode) =>
    new Promise<boolean>((resolve) => {
      Modal.confirm({
        title,
        content,
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

  const checkScanWarnings = async (skillName: string) => {
    await checkScanWarningsShared(
      skillName,
      api.getBlockedHistory,
      api.getSkillScanner,
      t,
    );
  };

  const toggleSelect = (name: string) => {
    setSelectedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const clearSelection = () => setSelectedSkills(new Set());

  // 分区切换：批量操作仅面向共享技能，切到「我的」时退出批量模式
  const handleScopeChange = (next: "shared" | "mine") => {
    setScopeFilter(next);
    if (batchModeEnabled) {
      clearSelection();
      setBatchModeEnabled(false);
    }
  };

  const selectAll = () =>
    setSelectedSkills(new Set(filteredSkills.map((s) => s.name)));

  const toggleBatchMode = () => {
    if (batchModeEnabled) {
      clearSelection();
      setBatchModeEnabled(false);
    } else {
      setBatchModeEnabled(true);
    }
  };

  const closePoolModal = () => setPoolModal(null);

  const handleUploadClick = () => fileInputRef.current?.click();

  // ── File upload ─────────────────────────────────────────────────────────

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.warning(t("skills.zipOnly"));
      return;
    }
    const sizeMB = file.size / (1024 * 1024);
    const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
    if (uploadLimit !== null && sizeMB > uploadLimit) {
      message.warning(
        t("skills.fileSizeExceeded", {
          limit: uploadLimit,
          size: sizeMB.toFixed(1),
        }),
      );
      return;
    }
    let renameMap: Record<string, string> | undefined;
    while (true) {
      const result = await uploadSkill(file, undefined, renameMap);
      if (result.success || !result.conflict) break;
      const conflicts = Array.isArray(result.conflict.conflicts)
        ? result.conflict.conflicts
        : [];
      if (conflicts.length === 0) break;
      const newRenames = await showConflictRenameModal(
        conflicts.map((c: { skill_name: string; suggested_name: string }) => ({
          key: c.skill_name,
          label: c.skill_name,
          suggested_name: c.suggested_name,
        })),
      );
      if (!newRenames) break;
      renameMap = { ...renameMap, ...newRenames };
    }
  };

  // ── Create / Edit / Delete ──────────────────────────────────────────────

  const handleCreate = () => {
    detailRequestIdRef.current += 1;
    setEditingSkill(null);
    setEditingSkillName("");
    setDrawerLoading(false);
    form.resetFields();
    form.setFieldsValue({ enabled: false, channels: ["all"], tags: [] });
    setDrawerOpen(true);
  };

  const closeImportModal = () => {
    if (importing) return;
    setImportModalOpen(false);
  };

  const handleConfirmImport = async (url: string, targetName?: string) => {
    const result = await importFromHub(url, targetName);
    if (result.success) {
      closeImportModal();
    } else if (result.conflict) {
      const detail = result.conflict;
      const suggested =
        detail?.suggested_name || detail?.conflicts?.[0]?.suggested_name;
      if (suggested) {
        const skillName =
          detail?.skill_name || detail?.conflicts?.[0]?.skill_name || "";
        const renameMap = await showConflictRenameModal([
          {
            key: skillName,
            label: skillName,
            suggested_name: String(suggested),
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleConfirmImport(url, newName);
        }
      }
    }
  };

  const handleEdit = async (skill: SkillSpec) => {
    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setEditingSkill(null);
    setEditingSkillName(skill.name);
    setDrawerLoading(true);
    form.resetFields();
    setDrawerOpen(true);
    try {
      if (skill.source === "personal") {
        const detail = await api.getPersonalSkill(skill.name, selectedAgent);
        if (detailRequestIdRef.current !== requestId) return;
        setEditingSkill({
          ...detail,
          channels: ["all"],
          tags: [],
          config: {},
        });
        return;
      }
      const detail = await api.getSkill(skill.name, selectedAgent);
      if (detailRequestIdRef.current !== requestId) return;
      setEditingSkill(detail);
    } catch (error) {
      if (detailRequestIdRef.current !== requestId) return;
      message.error(
        error instanceof Error ? error.message : t("skills.loadFailed"),
      );
      setDrawerOpen(false);
      setEditingSkillName("");
    } finally {
      if (detailRequestIdRef.current === requestId) {
        setDrawerLoading(false);
      }
    }
  };

  const handleToggleEnabled = async (
    skill: SkillSpec,
    e?: React.MouseEvent,
  ) => {
    e?.stopPropagation();
    if (skill.source === "personal") {
      await togglePersonalEnabled(skill);
      return;
    }
    await toggleEnabled(skill);
    await refreshSkills();
  };

  // 个人技能启停：拉取完整文件树后按 owner 身份回存（不走共享 enable/disable 闸门）
  const togglePersonalEnabled = async (skill: SkillSpec) => {
    try {
      const detail = await api.getPersonalSkill(skill.name, selectedAgent);
      await api.savePersonalSkill({
        name: skill.name,
        files: detail.files || { "SKILL.md": detail.content },
        enabled: !skill.enabled,
        agentId: selectedAgent,
      });
      message.success(
        skill.enabled
          ? t("skills.disabledSuccessfully")
          : t("skills.enabledSuccessfully"),
      );
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.operationFailed"),
      );
    }
  };

  const handleDelete = async (skill: SkillSpec, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (skill.source !== "personal") {
      await deleteSkill(skill);
      return;
    }
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("common.confirm"),
        content: t("skills.deleteConfirm"),
        okText: t("common.delete"),
        okType: "danger",
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      await api.deletePersonalSkill(skill.name, selectedAgent);
      message.success(t("skills.deleteSuccess"));
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.deleteFailed"),
      );
    }
  };

  // 发布为员工共享技能（S2→S1，需后端管理闸门）
  const handlePromote = async (skill: SkillSpec) => {
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("skills.promoteConfirmTitle"),
        content: t("skills.promoteConfirmContent", { name: skill.name }),
        okText: t("skills.promoteToShared"),
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      await api.promotePersonalSkill(skill.name, selectedAgent);
      message.success(t("skills.promoteSuccess"));
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.promoteFailed"),
      );
    }
  };

  const handleDrawerClose = () => {
    detailRequestIdRef.current += 1;
    setDrawerOpen(false);
    setEditingSkill(null);
    setEditingSkillName("");
    setDrawerLoading(false);
  };

  // ── Drawer submit ───────────────────────────────────────────────────────

  const handleSubmit = async (values: SkillDetail) => {
    // 个人技能（S2）保存：在「我的」分区新建，或编辑 source=personal。
    // owner 由后端强制为会话用户；files 全量回存，保留 references/scripts。
    const editingPersonal = editingSkill?.source === "personal";
    const creatingPersonal = !editingSkill && isPersonalScope;
    if (editingPersonal || creatingPersonal) {
      try {
        const baseFiles = editingPersonal ? editingSkill?.files || {} : {};
        await api.savePersonalSkill({
          name: values.name,
          files: { ...baseFiles, "SKILL.md": values.content },
          enabled: editingPersonal
            ? Boolean(editingSkill?.enabled ?? true)
            : true,
          agentId: selectedAgent,
        });
        message.success(
          editingPersonal
            ? t("common.save")
            : t("skills.createdSuccessfully"),
        );
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : t("skills.saveFailed"),
        );
      }
      return;
    }
    if (editingSkill) {
      const sourceName = editingSkill.name;
      const targetName = values.name;
      const saveEditedSkill = async (overwrite = false) => {
        const result = await api.saveSkill({
          name: targetName,
          content: values.content,
          source_name: sourceName !== targetName ? sourceName : undefined,
          config: values.config,
          overwrite,
        });
        const sideUpdates: Promise<unknown>[] = [];
        const newChannels = values.channels || ["all"];
        if (
          JSON.stringify(newChannels) !==
          JSON.stringify(editingSkill.channels || ["all"])
        ) {
          sideUpdates.push(api.updateSkillChannels(result.name, newChannels));
        }
        const newTags = values.tags || [];
        if (
          JSON.stringify(newTags) !== JSON.stringify(editingSkill.tags || [])
        ) {
          sideUpdates.push(api.updateSkillTags(result.name, newTags));
        }
        await Promise.all(sideUpdates);
        if (result.mode === "noop" && sideUpdates.length === 0) {
          setDrawerOpen(false);
          return;
        }
        if (result.mode !== "noop") {
          message.success(
            result.mode === "rename"
              ? `${t("common.save")}: ${result.name}`
              : t("common.save"),
          );
        }
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
      };
      try {
        await saveEditedSkill();
      } catch (error) {
        const detail = parseErrorDetail(error);
        if (detail?.reason === "conflict") {
          const confirmed = await confirmOverwrite(
            t("skillPool.overwriteConfirm"),
            <div style={{ display: "grid", gap: 8 }}>
              <div>{t("skills.overwriteExistingList")}</div>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>{targetName}</li>
              </ul>
            </div>,
          );
          if (!confirmed) return;
          try {
            await saveEditedSkill(true);
          } catch (retryError) {
            message.error(
              retryError instanceof Error
                ? retryError.message
                : t("common.save"),
            );
          }
        } else {
          message.error(
            error instanceof Error ? error.message : t("common.save"),
          );
        }
      }
    } else {
      const submitName = values.name;
      const result = await createSkill(
        submitName,
        values.content,
        values.config,
        true,
      );
      if (result.success) {
        const actualName = result.name || submitName;
        await Promise.all([
          api.updateSkillChannels(actualName, values.channels || ["all"]),
          ...(values.tags?.length
            ? [api.updateSkillTags(actualName, values.tags)]
            : []),
        ]);
        setDrawerOpen(false);
        invalidateSkillCache({ agentId: selectedAgent });
        await refreshSkills();
        return;
      }
      if (result.conflict?.suggested_name) {
        const renameMap = await showConflictRenameModal([
          {
            key: submitName,
            label: submitName,
            suggested_name: result.conflict!.suggested_name,
          },
        ]);
        if (renameMap) {
          const newName = Object.values(renameMap)[0];
          if (newName) await handleSubmit({ ...values, name: newName });
        }
      }
    }
  };

  // ── Pool transfer ───────────────────────────────────────────────────────

  const handleUploadToPool = async (workspaceSkillNames: string[]) => {
    if (workspaceSkillNames.length === 0) return;
    try {
      const conflictingNames: string[] = [];
      for (const skillName of workspaceSkillNames) {
        try {
          await api.uploadWorkspaceSkillToPool({
            workspace_id: selectedAgent,
            skill_name: skillName,
            preview_only: true,
          });
        } catch (error) {
          const detail = parseErrorDetail(error);
          if (detail?.reason === "conflict") {
            conflictingNames.push(skillName);
            continue;
          }
          throw error;
        }
      }
      if (conflictingNames.length > 0) {
        const confirmed = await confirmOverwrite(
          t("skillPool.overwriteConfirm"),
          <div style={{ display: "grid", gap: 8 }}>
            <div>{t("skills.overwriteExistingList")}</div>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {conflictingNames.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </div>,
        );
        if (!confirmed) return;
      }
      for (const skillName of workspaceSkillNames) {
        await api.uploadWorkspaceSkillToPool({
          workspace_id: selectedAgent,
          skill_name: skillName,
          overwrite: conflictingNames.includes(skillName),
        });
      }
      message.success(t("skills.uploadedToPool"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
      await refreshSkills();
      setPoolSkills(await api.listSkillPoolSkills());
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.uploadFailed"),
      );
    }
  };

  const handleDownloadFromPool = async (poolSkillNames: string[]) => {
    if (poolSkillNames.length === 0) return;
    try {
      const conflicts: DownloadConflict[] = [];
      for (const skillName of poolSkillNames) {
        try {
          await api.downloadSkillPoolSkill({
            skill_name: skillName,
            targets: [{ workspace_id: selectedAgent }],
            preview_only: true,
          });
        } catch (error) {
          const detail = parseErrorDetail(error);
          const returnedConflicts = Array.isArray(detail?.conflicts)
            ? detail.conflicts
            : [];
          if (!returnedConflicts.length) throw error;
          conflicts.push(
            ...returnedConflicts.map((conflict): DownloadConflict => {
              if (conflict?.reason === "builtin_upgrade") {
                return {
                  skill_name: conflict.skill_name || skillName,
                  reason: "builtin_upgrade" as const,
                  current_version_text: conflict.current_version_text || "",
                  source_version_text: conflict.source_version_text || "",
                };
              }
              if (conflict?.reason === "language_switch") {
                return {
                  skill_name: conflict.skill_name || skillName,
                  reason: "language_switch" as const,
                  source_language: conflict.source_language || "",
                  current_language: conflict.current_language || "",
                };
              }
              return {
                skill_name: conflict?.skill_name || skillName,
                reason: "conflict" as const,
              };
            }),
          );
        }
      }
      if (conflicts.length > 0) {
        const allBuiltinUpgrades = conflicts.every(
          (c) => c.reason === "builtin_upgrade",
        );
        const allLanguageSwitch = conflicts.every(
          (c) => c.reason === "language_switch",
        );
        const title = allBuiltinUpgrades
          ? t("skills.builtinUpgradeTitle")
          : allLanguageSwitch
          ? t("skills.languageSwitchTitle")
          : t("skillPool.overwriteConfirm");
        const subtitle = allBuiltinUpgrades
          ? t("skillPool.builtinOverwriteTargetsContent")
          : allLanguageSwitch
          ? t("skills.languageSwitchContent")
          : t("skills.overwriteExistingList");
        const confirmed = await confirmOverwrite(
          title,
          <div style={{ display: "grid", gap: 8 }}>
            <div>{subtitle}</div>
            {conflicts.map((conflict) => (
              <div key={conflict.skill_name}>
                <strong>{conflict.skill_name}</strong>
                {conflict.reason === "builtin_upgrade" ? (
                  <>
                    {"  "}
                    {t("skillPool.currentVersion")}:{" "}
                    {conflict.current_version_text || "-"}
                    {"  ->  "}
                    {t("skillPool.sourceVersion")}:{" "}
                    {conflict.source_version_text || "-"}
                  </>
                ) : null}
                {conflict.reason === "language_switch" ? (
                  <>
                    {"  "}
                    {conflict.current_language === "zh"
                      ? t("skillPool.langZh")
                      : t("skillPool.langEn")}
                    {"  →  "}
                    {conflict.source_language === "zh"
                      ? t("skillPool.langZh")
                      : t("skillPool.langEn")}
                  </>
                ) : null}
              </div>
            ))}
          </div>,
        );
        if (!confirmed) return;
      }
      for (const skillName of poolSkillNames) {
        const shouldOverwrite = conflicts.some(
          (c) => c.skill_name === skillName,
        );
        await api.downloadSkillPoolSkill({
          skill_name: skillName,
          targets: [{ workspace_id: selectedAgent }],
          overwrite: shouldOverwrite,
        });
      }
      message.success(t("skills.downloadedToWorkspace"));
      closePoolModal();
      invalidateSkillCache({ agentId: selectedAgent, pool: true });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("common.download") + " failed",
      );
    }
  };

  // ── Batch enable / disable ───────────────────────────────────────────────

  const handleBatchEnable = async () => {
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    try {
      const { results } = await api.batchEnableSkills(names);
      const entries = Object.entries(results);
      const succeeded = entries
        .filter(([, r]) => r.success)
        .map(([name]) => name);
      const failed = entries.filter(([, r]) => r.success === false);
      for (const [, result] of failed) {
        const detail = result.detail;
        if (result.reason !== "security_scan_failed" || !detail) continue;
        showScanErrorModal(detail as SecurityScanErrorResponse, t);
      }
      if (failed.length > 0) {
        message.warning(
          t("skills.batchEnablePartial", {
            enabled: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchEnableSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
      for (const name of succeeded) {
        await checkScanWarnings(name);
      }
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.batchEnableFailed"),
      );
    }
  };

  const handleBatchDisable = async () => {
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    try {
      const { results } = await api.batchDisableSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skills.batchDisablePartial", {
            disabled: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchDisableSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.batchDisableFailed"),
      );
    }
  };

  // ── Batch delete ────────────────────────────────────────────────────────

  const handleBatchDelete = async () => {
    const names = Array.from(selectedSkills);
    if (names.length === 0) return;
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("skills.batchDeleteTitle", { count: names.length }),
        content: (
          <ul style={{ margin: "8px 0", paddingLeft: 20 }}>
            {names.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ),
        okText: t("common.delete"),
        okType: "danger",
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!confirmed) return;
    try {
      const { results } = await api.batchDeleteSkills(names);
      const failed = Object.entries(results).filter(([, r]) => !r.success);
      if (failed.length > 0) {
        message.warning(
          t("skills.batchDeletePartial", {
            deleted: names.length - failed.length,
            failed: failed.length,
          }),
        );
      } else {
        message.success(
          t("skills.batchDeleteSuccess", { count: names.length }),
        );
      }
      clearSelection();
      invalidateSkillCache({ agentId: selectedAgent });
      await refreshSkills();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("skills.batchDeleteFailed"),
      );
    }
  };

  return {
    skills,
    providerSkills,
    sortedSkills,
    visibleSkills,
    hasMore,
    sentinelRef,
    poolSkills,
    allTags,
    filteredSkills,
    scopedSkills,
    conflictRenameModal,
    loading,
    uploading,
    importing,
    scopeEnabled,
    scopeFilter,
    isPersonalScope,
    handleScopeChange,
    handlePromote,
    drawerOpen,
    drawerLoading,
    editingSkillName,
    importModalOpen,
    setImportModalOpen,
    editingSkill,
    form,
    fileInputRef,
    poolModal,
    setPoolModal,
    selectedSkills,
    batchModeEnabled,
    viewMode,
    setViewMode,
    filterOpen,
    setFilterOpen,
    searchQuery,
    setSearchQuery,
    searchTags,
    setSearchTags,
    handleCreate,
    handleEdit,
    handleToggleEnabled,
    handleDelete,
    handleDrawerClose,
    handleSubmit,
    handleUploadToPool,
    handleDownloadFromPool,
    handleBatchEnable,
    handleBatchDisable,
    handleBatchDelete,
    handleUploadClick,
    handleFileChange,
    handleConfirmImport,
    closeImportModal,
    closePoolModal,
    toggleSelect,
    clearSelection,
    selectAll,
    toggleBatchMode,
    toggleEnabled,
    refreshSkills,
    hardRefresh,
    cancelImport,
  };
}
