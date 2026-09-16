import {
  Boxes,
  ChevronDown,
  CircleDot,
  LoaderCircle,
  MessageCircleQuestion,
  Rocket,
  Settings2,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { Popover, Tooltip } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import {
  DEFAULT_LOOP_MODE,
  fetchAvailableLoopModes,
  type LoopModeInfo,
  useLoopStore,
} from "../../stores/loopStore";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useWorkbenchSandboxAid } from "../../utils/workbenchSandbox";
import { OsDrawer } from "../../os/OsOverlay";
import { InlineMarkdown } from "../Markdown/InlineMarkdown";
import {
  resolveLoopModeDescriptionMarkdown,
  resolveLoopModeName,
} from "../../utils/loopModeDescription";
import styles from "./index.module.less";

function ModeIcon({ mode, size = 14 }: { mode: LoopModeInfo; size?: number }) {
  if (mode.id === "goal") return <Target size={size} />;
  if (mode.id === "mission") return <Rocket size={size} />;
  if (mode.source === "custom") return <Sparkles size={size} />;
  if (mode.source === "plugin") return <Boxes size={size} />;
  return <CircleDot size={size} />;
}

interface LoopModeSelectorProps {
  className?: string;
  compact?: boolean;
  /** 紧凑形态下在图标旁显示模式名（如“默认”），
   * 用于窄容器桌面场景；触屏紧凑形态仍仅图标。 */
  shortLabel?: boolean;
}

export function LoopModeSelector({
  className,
  compact = false,
  shortLabel = false,
}: LoopModeSelectorProps = {}) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language || "en";
  const navigate = useNavigate();
  // 工作台 MemoryRouter 沙箱内 Chat 会把路径改写成 /chat/*，
  // 无法靠 location 判断，改由沙箱上下文下发员工 id。
  const sandboxAid = useWorkbenchSandboxAid();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const availableModes = useLoopStore((state) => state.availableModes);
  const selectedModeId = useLoopStore((state) => state.selectedModeId);
  const sessionState = useLoopStore((state) => state.sessionState);
  const activeMode = useLoopStore((state) => state.activeMode);
  const catalogLoading = useLoopStore((state) => state.catalogLoading);
  const catalogError = useLoopStore((state) => state.catalogError);
  const setSelectedMode = useLoopStore((state) => state.setSelectedMode);

  const selectedMode =
    availableModes.find((mode) => mode.id === selectedModeId) ??
    DEFAULT_LOOP_MODE;
  const builtInModes = useMemo(
    () => availableModes.filter((mode) => mode.source === "builtin"),
    [availableModes],
  );
  const extendedModes = useMemo(
    () => availableModes.filter((mode) => mode.source !== "builtin"),
    [availableModes],
  );

  if (sessionState !== "idle" && activeMode) {
    const modeName = resolveLoopModeName(activeMode, t, lang);
    const tooltip =
      activeMode.source === "custom"
        ? t("loop.activeCustomDescription")
        : t("loop.activePersistentDescription");
    return (
      <Tooltip title={tooltip}>
        <div
          className={[styles.activeMode, className].filter(Boolean).join(" ")}
          aria-label={`${modeName} ${t(`loop.${sessionState}`)}`}
          aria-live="polite"
          data-state={sessionState}
        >
          {sessionState === "starting" && (
            <LoaderCircle className={styles.spin} size={14} />
          )}
          {sessionState === "running" && <ModeIcon mode={activeMode} />}
          {sessionState === "awaiting_user" && (
            <MessageCircleQuestion size={14} />
          )}
          {compact && shortLabel && (
            <span className={styles.triggerShortName}>{modeName}</span>
          )}
          {!compact && (
            <>
              <span>{modeName}</span>
              <span className={styles.activeState}>
                {t(`loop.${sessionState}`)}
              </span>
            </>
          )}
        </div>
      </Tooltip>
    );
  }

  const renderGroup = (title: string, modes: LoopModeInfo[]) => {
    if (modes.length === 0) return null;
    return (
      <section className={styles.modeGroup}>
        <div className={styles.groupLabel}>{title}</div>
        {modes.map((mode) => {
          const selected = mode.id === selectedMode.id;
          return (
            <button
              aria-selected={selected}
              className={`${styles.modeOption} ${
                selected ? styles.selected : ""
              }`}
              key={mode.id}
              onClick={() => {
                setSelectedMode(mode.id);
                setOpen(false);
              }}
              role="option"
              type="button"
            >
              <span className={styles.optionIcon}>
                <ModeIcon mode={mode} size={16} />
              </span>
              <span className={styles.optionCopy}>
                <span className={styles.optionName}>
                  {resolveLoopModeName(mode, t, lang)}
                </span>
                <span className={styles.optionDescription}>
                  <InlineMarkdown
                    markdown={resolveLoopModeDescriptionMarkdown(mode, t, lang)}
                  />
                </span>
              </span>
              {selected ? <CircleDot size={15} /> : null}
            </button>
          );
        })}
      </section>
    );
  };

  const settingsButton = (
    <button
      aria-label={t("loop.gotoSettings")}
      className={styles.settingsButton}
      onClick={() => {
        setOpen(false);
        // 沙箱内没有 /agent-config 路由：直跳会被沙箱 CatchAllNavigate
        // 弹回档案页（按钮看似失效）；沙箱内改跳运维组 config 子页
        // 并保留 tab 参数，沙箱外仍走 /agent-config 的 agent 作用域重定向。
        navigate(
          sandboxAid
            ? `/studio/${sandboxAid}/ops/config?tab=agentLoop`
            : "/agent-config?tab=agentLoop",
        );
      }}
      type="button"
    >
      <Settings2 size={16} />
    </button>
  );

  const content = (
    <div className={styles.modeMenu}>
      <div className={styles.menuHeader}>
        <div>
          <div className={styles.menuTitle}>{t("loop.selectorTitle")}</div>
          <div className={styles.menuHint}>{t("loop.selectorHint")}</div>
        </div>
        <div className={styles.menuActions}>
          {isMobile ? (
            settingsButton
          ) : (
            <Tooltip title={t("loop.gotoSettings")}>{settingsButton}</Tooltip>
          )}
          {isMobile && (
            <button
              aria-label={t("common.close")}
              className={styles.settingsButton}
              onClick={() => setOpen(false)}
              type="button"
            >
              <X size={18} />
            </button>
          )}
        </div>
      </div>
      <div className={styles.modeList} role="listbox">
        {renderGroup(t("loop.builtInModes"), builtInModes)}
        {renderGroup(t("loop.customModes"), extendedModes)}
        {catalogError ? (
          <div className={styles.menuError}>
            <span>{t("loop.loadError")}</span>
            <button
              onClick={() => void fetchAvailableLoopModes()}
              type="button"
            >
              {t("loop.retry")}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );

  const selectedModeName = resolveLoopModeName(selectedMode, t, lang);

  const triggerButton = (
    <button
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-label={t("loop.selectorAria")}
      className={[styles.modeTrigger, className].filter(Boolean).join(" ")}
      disabled={catalogLoading && availableModes.length === 0}
      onClick={isMobile ? () => setOpen((current) => !current) : undefined}
      type="button"
    >
      {catalogLoading ? (
        <LoaderCircle className={styles.spin} size={14} />
      ) : (
        <ModeIcon mode={selectedMode} />
      )}
      {compact && shortLabel && (
        <span className={styles.triggerShortName}>{selectedModeName}</span>
      )}
      {!compact && (
        <>
          <span>{selectedModeName}</span>
          <ChevronDown size={13} />
        </>
      )}
    </button>
  );

  // 紧凑形态隐藏了标签与箭头，用 Tooltip 补回当前模式名的可见性
  const desktopTrigger = compact ? (
    <Tooltip title={selectedModeName}>{triggerButton}</Tooltip>
  ) : (
    triggerButton
  );

  if (isMobile) {
    return (
      <>
        {triggerButton}
        <OsDrawer
          aria-label={t("loop.selectorTitle")}
          open={open}
          placement="bottom"
          height="auto"
          closable={false}
          destroyOnHidden
          rootClassName={styles.modeDrawer}
          onClose={() => setOpen(false)}
          styles={{
            body: { padding: 0, overflow: "hidden" },
            content: {
              borderRadius: "14px 14px 0 0",
              overflow: "hidden",
            },
            wrapper: { maxHeight: "min(48dvh, 400px)" },
          }}
        >
          {content}
        </OsDrawer>
      </>
    );
  }

  return (
    <Popover
      arrow={false}
      content={content}
      onOpenChange={setOpen}
      open={open}
      classNames={{ root: styles.modePopover }}
      placement="topLeft"
      trigger="click"
    >
      {desktopTrigger}
    </Popover>
  );
}
