/**
 * LoopModeSelector — backend-parity execution-mode picker. Non-default modes
 * are applied as a "/{slash_command}" message prefix (the backend loop
 * contract), so the trigger shows the blue-pill look from the console
 * composer when a persistent mode is selected. Names/descriptions resolve
 * through the console i18n chain (builtin zh table → plugin zh → raw).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { loopApi, type LoopModeInfo } from "../../api/modules";
import {
  DEFAULT_LOOP_MODE,
  getSelectedLoopMode,
  resolveLoopModeDescription,
  resolveLoopModeName,
  useChatPrefs,
} from "../../stores/chatPrefs";

function modeIcon(mode: LoopModeInfo): string {
  if (mode.id === "goal") return "fa-solid fa-bullseye";
  if (mode.id === "mission") return "fa-solid fa-rocket";
  if (mode.source === "custom") return "fa-solid fa-wand-magic-sparkles";
  if (mode.source === "plugin") return "fa-solid fa-cubes";
  return "fa-solid fa-circle-dot";
}

export default function LoopModeSelector() {
  const loopModes = useChatPrefs((s) => s.loopModes);
  const loopModeId = useChatPrefs((s) => s.loopModeId);
  const setLoopMode = useChatPrefs((s) => s.setLoopMode);
  const setLoopModes = useChatPrefs((s) => s.setLoopModes);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || loopModes.length > 1) return;
    setLoading(true);
    loopApi
      .list()
      .then((modes) => {
        if (Array.isArray(modes) && modes.length > 0) {
          setLoopModes(modes);
        }
      })
      .catch(() => {
        // keep the default-only catalog
      })
      .finally(() => setLoading(false));
  }, [open, loopModes.length, setLoopModes]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = getSelectedLoopMode(loopModes, loopModeId);
  const groups = useMemo(() => {
    const builtin = loopModes.filter((m) => m.source === "builtin");
    const extended = loopModes.filter((m) => m.source !== "builtin");
    return { builtin, extended };
  }, [loopModes]);

  const renderOption = (mode: LoopModeInfo) => {
    const isActive = mode.id === selected.id;
    return (
      <button
        type="button"
        key={mode.id}
        className={`loop-option${isActive ? " active" : ""}`}
        onClick={() => {
          setLoopMode(mode.id);
          setOpen(false);
        }}
      >
        <i className={modeIcon(mode)} />
        <span className="loop-option-copy">
          <span className="loop-option-name">{resolveLoopModeName(mode)}</span>
          <span className="loop-option-desc">
            {resolveLoopModeDescription(mode)}
          </span>
        </span>
        {isActive && <i className="fa-solid fa-circle-check ms-check" />}
      </button>
    );
  };

  const isDefault = selected.id === DEFAULT_LOOP_MODE.id;

  return (
    <div className="loop-selector" ref={rootRef}>
      <button
        type="button"
        className={`loop-trigger${!isDefault ? " accent" : ""}${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="选择执行模式"
      >
        {loading ? (
          <i className="fa-solid fa-spinner fa-spin" />
        ) : (
          <i className={modeIcon(selected)} />
        )}
        <span>{resolveLoopModeName(selected)}</span>
        <i className="fa-solid fa-chevron-down ms-caret" />
      </button>

      {open && (
        <div className="loop-panel">
          <div className="loop-panel-header">
            <div>
              <div className="loop-panel-title">Loop 模式</div>
              <div className="loop-panel-hint">
                选择智能体接下来的工作方式
              </div>
            </div>
          </div>
          {groups.builtin.length > 0 && (
            <div className="loop-group-label">内置</div>
          )}
          {groups.builtin.map(renderOption)}
          {groups.extended.length > 0 && (
            <div className="loop-group-label">自定义与插件</div>
          )}
          {groups.extended.map(renderOption)}
        </div>
      )}
    </div>
  );
}
