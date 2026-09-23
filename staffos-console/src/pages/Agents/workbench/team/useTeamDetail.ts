/**
 * useTeamDetail — 专家团工作台详情数据 hook。
 *
 * 并行拉取团队记录 / 能力投影 / 发布版本 / 配置元数据；metadata 与
 * 团队无关，模块级缓存 + in-flight 去重（全团队共享一份请求）。
 * 团队记录缺失时整页不可用（错误按 404/403/其他分类）；能力投影、
 * 版本与元数据失败各自降级为空值，但通过分区 status/error 明确区分
 * “没有数据”和“数据获取失败”，不伪装成零值。
 */
import { useCallback, useEffect, useState } from "react";
import { adminExpertTeamsApi } from "../../../../api/modules/admin";
import type {
  ExpertTeamRecord,
  MemberUpdateItem,
  TeamCapabilityMember,
  TeamMetadata,
  TeamVersionRow,
} from "../../../../api/modules/admin";

export type TeamDetailErrorKind = "not_found" | "forbidden" | "other";

export interface TeamDetailError {
  kind: TeamDetailErrorKind;
  message: string;
}

export type SectionStatus = "loading" | "ok" | "error";

// metadata 是全局枚举源：模块级缓存 + in-flight 去重，避免每个团队重复拉取。
let metadataCache: TeamMetadata | null = null;
let metadataInflight: Promise<TeamMetadata> | null = null;

function loadMetadata(): Promise<TeamMetadata> {
  if (metadataCache) {
    return Promise.resolve(metadataCache);
  }
  if (!metadataInflight) {
    metadataInflight = adminExpertTeamsApi
      .metadata()
      .then((meta) => {
        metadataCache = meta;
        return meta;
      })
      .finally(() => {
        metadataInflight = null;
      });
  }
  return metadataInflight;
}

/** 按 HTTP 状态分类降级信号（request.ts 为错误对象挂了 status 属性）。 */
function classifyError(err: unknown): TeamDetailError {
  const status = (err as Error & { status?: number })?.status;
  if (status === 404) {
    return { kind: "not_found", message: String(err) };
  }
  if (status === 403) {
    return { kind: "forbidden", message: String(err) };
  }
  return { kind: "other", message: String(err) };
}

export interface TeamDetailState {
  team: ExpertTeamRecord | null;
  members: TeamCapabilityMember[];
  versions: TeamVersionRow[];
  metadata: TeamMetadata | null;
  /** 成员升级提醒（可空；失败不阻塞页面）。 */
  memberUpdates: MemberUpdateItem[];
  loading: boolean;
  error: TeamDetailError | null;
  // ── 分区状态：能力/版本/升级提醒各自独立失败，不伪装成零值 ──
  capabilitiesStatus: SectionStatus;
  capabilitiesError: string;
  versionsStatus: SectionStatus;
  versionsError: string;
  memberUpdatesStatus: SectionStatus;
  memberUpdatesError: string;
  /** 手动刷新或外部事件触发后重新拉取全部分区数据。 */
  refresh: () => void;
}

export function useTeamDetail(teamId: string): TeamDetailState {
  const [refreshVersion, setRefreshVersion] = useState(0);
  const refresh = useCallback(() => setRefreshVersion((v) => v + 1), []);

  const [state, setState] = useState<Omit<TeamDetailState, "refresh">>({
    team: null,
    members: [],
    versions: [],
    metadata: null,
    memberUpdates: [],
    loading: true,
    error: null,
    capabilitiesStatus: "loading",
    capabilitiesError: "",
    versionsStatus: "loading",
    versionsError: "",
    memberUpdatesStatus: "loading",
    memberUpdatesError: "",
  });

  useEffect(() => {
    if (!teamId) {
      return;
    }
    let alive = true;
    setState((prev) => ({
      ...prev,
      loading: true,
      error: null,
      capabilitiesStatus: "loading",
      capabilitiesError: "",
      versionsStatus: "loading",
      versionsError: "",
      memberUpdatesStatus: "loading",
      memberUpdatesError: "",
    }));
    Promise.all([
      adminExpertTeamsApi.get(teamId),
      adminExpertTeamsApi.capabilities(teamId).catch(() => null),
      adminExpertTeamsApi.versions(teamId).catch(() => null),
      loadMetadata().catch(() => null),
      adminExpertTeamsApi.memberUpdates(teamId).catch(() => null),
    ])
      .then(([record, caps, versionRows, meta, updates]) => {
        if (!alive) {
          return;
        }
        setState({
          team: record,
          members: caps?.members ?? [],
          versions: versionRows ?? [],
          metadata: meta,
          memberUpdates: updates ?? [],
          loading: false,
          error: null,
          // 分区状态：区分“空数据”和“请求失败”
          capabilitiesStatus: caps ? "ok" : "error",
          capabilitiesError: caps ? "" : "能力投影加载失败",
          versionsStatus: versionRows ? "ok" : "error",
          versionsError: versionRows ? "" : "版本记录加载失败",
          memberUpdatesStatus: updates ? "ok" : "error",
          memberUpdatesError: updates ? "" : "升级提醒加载失败",
        });
      })
      .catch((err) => {
        if (!alive) {
          return;
        }
        setState((prev) => ({
          ...prev,
          loading: false,
          error: classifyError(err),
        }));
      });
    return () => {
      alive = false;
    };
  }, [teamId, refreshVersion]);

  // 跨组件通知：TeamChangeCard 确认/拒绝后 dispatch 本事件，
  // 仅当 detail.teamId 匹配当前团队时触发刷新。
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ teamId?: string }>).detail;
      if (detail?.teamId === teamId) {
        refresh();
      }
    };
    window.addEventListener("qwenpaw:team-config-changed", handler);
    return () => window.removeEventListener("qwenpaw:team-config-changed", handler);
  }, [teamId, refresh]);

  // 15 秒兜底轮询：事件总线是进程内的，丢事件或跨 worker 时靠轮询兜底。
  // 页面不可见时跳过查询，恢复可见后下一个周期自动拉取。
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") {
        refresh();
      }
    }, 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  return { ...state, refresh };
}
