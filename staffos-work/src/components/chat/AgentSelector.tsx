/**
 * AgentSelector — picks the agent every chat request targets via the
 * X-Agent-Id header (same identity model as the console sidebar). Shows
 * the pink agent-id chip + orange "Agent {name}" label seen in the
 * backend composer footer.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentApi, type AgentSummary } from "../../api/modules";
import { useChatPrefs } from "../../stores/chatPrefs";

export default function AgentSelector() {
  const selectedAgent = useChatPrefs((s) => s.selectedAgent);
  const setSelectedAgent = useChatPrefs((s) => s.setSelectedAgent);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const res = await agentApi.list();
      setAgents(res.agents ?? []);
    } catch {
      // the default agent always works even when listing fails
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

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

  const current = useMemo(
    () => agents.find((a) => a.id === selectedAgent),
    [agents, selectedAgent],
  );

  return (
    <div className="agent-selector" ref={rootRef}>
      <button
        type="button"
        className={`agent-trigger${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="选择对话的 Agent"
      >
        <span className="agent-id-chip">{selectedAgent}</span>
        <span className="agent-name-label">Agent {current?.name ?? "默认"}</span>
        <i className="fa-solid fa-chevron-down ms-caret" />
      </button>

      {open && (
        <div className="agent-panel">
          {agents.length === 0 ? (
            <div className="ms-empty">加载中…</div>
          ) : (
            agents.map((a) => {
              const isActive = a.id === selectedAgent;
              return (
                <button
                  type="button"
                  key={a.id}
                  className={`agent-option${isActive ? " active" : ""}`}
                  onClick={() => {
                    setSelectedAgent(a.id);
                    setOpen(false);
                  }}
                >
                  <span className="agent-option-copy">
                    <span className="agent-option-name">{a.name}</span>
                    <span className="agent-option-desc">
                      {a.description || a.id}
                    </span>
                  </span>
                  {!a.enabled && <span className="ms-tag">未启用</span>}
                  {isActive && <i className="fa-solid fa-check ms-check" />}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
