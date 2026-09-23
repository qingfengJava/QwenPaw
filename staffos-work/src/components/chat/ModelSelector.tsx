/**
 * ModelSelector — backend-parity model picker for the console chat plane.
 * Same data contract as the console ModelSelector (GET /models, GET/PUT
 * /models/active with agent scope): PRO/FREE tabs, provider groups with
 * collapse, search, free/vision tags and an active check. Switching calls
 * the slot API so the very next SSE turn runs on the new model.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  providerApi,
  type ModelInfo,
  type ProviderInfo,
} from "../../api/modules";
import { useToast } from "../Toast";

const PROVIDER_COLORS = [
  "#10a37f",
  "#3b6ef6",
  "#ff7f16",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
  "#f59e0b",
  "#6366f1",
];

function providerColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return PROVIDER_COLORS[Math.abs(hash) % PROVIDER_COLORS.length];
}

function ProviderBadge({ id, size = 16 }: { id: string; size?: number }) {
  return (
    <span
      className="ms-provider-badge"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.55,
        background: providerColor(id),
      }}
    >
      {id.slice(0, 1).toUpperCase()}
    </span>
  );
}

interface EligibleProvider {
  id: string;
  name: string;
  models: ModelInfo[];
  has_api_key: boolean;
  require_api_key?: boolean;
  is_custom?: boolean;
  is_local?: boolean;
  is_free_tier?: boolean;
}

export default function ModelSelector({
  agentId,
  onActiveChange,
}: {
  agentId: string;
  /** Notifies the composer about the effective context window. */
  onActiveChange?: (maxInputLength: number | null) => void;
}) {
  const toast = useToast();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [active, setActive] = useState<{
    provider_id: string;
    model: string;
  } | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"pro" | "free">(
    () =>
      (localStorage.getItem("xian_model_tab") as "pro" | "free") || "pro",
  );
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState<Record<string, number>>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const refreshActive = useCallback(async () => {
    try {
      const info = await providerApi.active(agentId);
      if (info.active_llm) {
        setActive(info.active_llm);
      }
      onActiveChange?.(info.effective_max_input_length ?? null);
    } catch {
      // keep last known active; header still renders the fallback label
    }
  }, [agentId, onActiveChange]);

  useEffect(() => {
    void refreshActive();
  }, [refreshActive]);

  // Close on outside click / Esc.
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
    window.setTimeout(() => searchRef.current?.focus(), 40);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    try {
      const list = await providerApi.list();
      if (Array.isArray(list)) setProviders(list);
    } catch {
      // leave the panel to show its empty hint
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpen = async (next: boolean) => {
    setOpen(next);
    if (next) {
      void loadProviders();
      void refreshActive();
    } else {
      setSearch("");
    }
  };

  // Eligible providers mirror the console filter: configured key, no-key
  // providers, custom/local providers, or free-tier entries.
  const eligible: EligibleProvider[] = useMemo(
    () =>
      providers
        .filter((p) => {
          const all = [...(p.models ?? []), ...(p.extra_models ?? [])];
          if (p.is_free_tier) return true;
          if (all.length === 0) return false;
          if (p.require_api_key === false) return !!p.base_url;
          if (p.is_custom) return !!p.base_url;
          if (p.require_api_key ?? true) return !!p.api_key;
          return true;
        })
        .map((p) => ({
          id: p.id,
          name: p.name,
          models: [...(p.models ?? []), ...(p.extra_models ?? [])],
          has_api_key: !!p.api_key,
          require_api_key: p.require_api_key,
          is_custom: p.is_custom,
          is_local: p.is_local,
          is_free_tier: p.is_free_tier,
        })),
    [providers],
  );

  const { freeProviders, proProviders } = useMemo(() => {
    const freeMap = new Map<string, EligibleProvider>();
    const proMap = new Map<string, EligibleProvider>();
    for (const p of eligible) {
      const freeModels = p.models.filter((m) => m.is_free);
      const proModels = p.models.filter((m) => !m.is_free);
      if (freeModels.length > 0 || (p.is_free_tier && p.models.length === 0)) {
        freeMap.set(p.id, { ...p, models: freeModels });
      }
      if (
        proModels.length > 0 &&
        (p.has_api_key ||
          p.require_api_key === false ||
          p.is_custom ||
          p.is_local)
      ) {
        proMap.set(p.id, { ...p, models: proModels });
      }
    }
    return {
      freeProviders: [...freeMap.values()],
      proProviders: [...proMap.values()],
    };
  }, [eligible]);

  const query = search.trim().toLowerCase();
  const filterList = (list: EligibleProvider[]) => {
    if (!query) return list;
    return list
      .map((p) => ({
        ...p,
        models: p.models.filter(
          (m) =>
            (m.name || m.id).toLowerCase().includes(query) ||
            p.name.toLowerCase().includes(query),
        ),
      }))
      .filter(
        (p) => p.models.length > 0 || p.name.toLowerCase().includes(query),
      );
  };

  const activeName = (() => {
    if (!active) return "选择模型";
    const provider = eligible.find((p) => p.id === active.provider_id);
    const model = provider?.models.find((m) => m.id === active.model);
    return model?.name || model?.id || active.model;
  })();

  const handleSelect = async (providerId: string, modelId: string) => {
    if (saving) return;
    if (active?.provider_id === providerId && active.model === modelId) {
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      const updated = await providerApi.setActive(providerId, modelId, agentId);
      setActive(updated.active_llm ?? { provider_id: providerId, model: modelId });
      onActiveChange?.(updated.effective_max_input_length ?? null);
      setOpen(false);
      toast.success("模型已切换");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "模型切换失败");
    } finally {
      setSaving(false);
    }
  };

  const renderGroup = (p: EligibleProvider) => {
    const isCollapsed = collapsed.has(p.id);
    const count = visibleCount[p.id] ?? 5;
    const visible = p.models.slice(0, count);
    const remaining = p.models.length - count;
    return (
      <div key={p.id} className="ms-provider-group">
        <button
          type="button"
          className="ms-provider-header"
          onClick={() =>
            setCollapsed((prev) => {
              const next = new Set(prev);
              if (next.has(p.id)) {
                next.delete(p.id);
              } else {
                next.add(p.id);
              }
              return next;
            })
          }
        >
          <ProviderBadge id={p.id} />
          <span className="ms-provider-name">{p.name}</span>
          <i
            className={`fa-solid fa-chevron-${isCollapsed ? "down" : "up"} ms-caret`}
          />
        </button>
        {!isCollapsed && (
          <>
            {visible.map((m) => {
              const isActive =
                active?.provider_id === p.id && active.model === m.id;
              return (
                <button
                  type="button"
                  key={m.id}
                  className={`ms-model-item${isActive ? " active" : ""}`}
                  onClick={() => void handleSelect(p.id, m.id)}
                >
                  <span className="ms-model-name">{m.name || m.id}</span>
                  <span className="ms-model-tags">
                    {m.is_free && <span className="ms-tag free">FREE</span>}
                    {(m.supports_image || m.supports_multimodal) && (
                      <span className="ms-tag vision">视觉</span>
                    )}
                    {isActive && <i className="fa-solid fa-check ms-check" />}
                  </span>
                </button>
              );
            })}
            {remaining > 0 && (
              <button
                type="button"
                className="ms-view-more"
                onClick={(e) => {
                  e.stopPropagation();
                  setVisibleCount((prev) => ({
                    ...prev,
                    [p.id]: count + 10,
                  }));
                }}
              >
                查看更多（{Math.min(10, remaining)}）
              </button>
            )}
          </>
        )}
      </div>
    );
  };

  const list =
    tab === "free" ? filterList(freeProviders) : filterList(proProviders);

  return (
    <div className="model-selector" ref={rootRef}>
      <button
        type="button"
        className={`ms-trigger${open ? " open" : ""}`}
        onClick={() => void handleOpen(!open)}
        title="选择模型"
      >
        {saving ? (
          <i className="fa-solid fa-spinner fa-spin" />
        ) : (
          active && <ProviderBadge id={active.provider_id} size={14} />
        )}
        <span className="ms-trigger-name">{activeName}</span>
        <i className="fa-solid fa-chevron-down ms-caret" />
      </button>

      {open && (
        <div className="ms-panel">
          <div className="ms-search">
            <i className="fa-solid fa-magnifying-glass" />
            <input
              ref={searchRef}
              value={search}
              placeholder="搜索模型"
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button type="button" onClick={() => setSearch("")}>
                <i className="fa-solid fa-circle-xmark" />
              </button>
            )}
          </div>
          <div className="ms-tabs">
            <button
              type="button"
              className={tab === "pro" ? "active" : ""}
              onClick={() => {
                setTab("pro");
                localStorage.setItem("xian_model_tab", "pro");
              }}
            >
              PRO
            </button>
            <button
              type="button"
              className={tab === "free" ? "active" : ""}
              onClick={() => {
                setTab("free");
                localStorage.setItem("xian_model_tab", "free");
              }}
            >
              FREE
            </button>
          </div>
          <div className="ms-list">
            {loading ? (
              <div className="ms-empty">
                <i className="fa-solid fa-spinner fa-spin" /> 加载中…
              </div>
            ) : list.length === 0 ? (
              <div className="ms-empty">
                {query ? "没有匹配的模型" : "暂无可用模型，请先在后台配置模型服务商"}
              </div>
            ) : (
              <>
                {tab === "free" && (
                  <div className="ms-banner free">
                    <i className="fa-solid fa-triangle-exclamation" />
                    免费额度模型，适合体验与轻量使用
                  </div>
                )}
                {tab === "pro" && (
                  <div className="ms-banner pro">已配置服务商用完即止，按用量计费</div>
                )}
                {list.map(renderGroup)}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
