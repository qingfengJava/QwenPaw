import { useCallback, useEffect, useRef, useState } from "react";
import api from "../../../api";
import { invalidateSkillCache } from "../../../api/modules/skill";
import type { MarketResult } from "../../../api/modules/market";
import { notifySkillChange } from "../../../utils/skillChangeEvents";

export type InstallTarget = "pool" | "workspace";

export type InstallStatus =
  | "queued"
  | "installing"
  | "completed"
  | "failed"
  | "cancelled";

export interface InstallQueueItem {
  id: string;
  result: MarketResult;
  target: InstallTarget;
  status: InstallStatus;
  message: string;
  installedName?: string;
  /** workspace 模式下的目标智能体 ID（队列展示 + 冲突定位） */
  targetAgentId?: string;
  /** pool 模式下入池后需立即分发的智能体 ID（员工技能页入口） */
  deliverAgentId?: string;
  /** 冲突时后端建议的新名称，展示后可一键采用重试 */
  suggestedName?: string;
  /** retry 时指定的覆盖名称，出队安装时作为 target_name 传入 */
  retryName?: string;
}

export interface UseMarketInstallOptions {
  selectedAgent: string;
  /** 员工技能页入口传入：pool 安装成功后自动分发给该智能体 */
  deliverAgentId?: string;
  onSuccess?: (item: InstallQueueItem) => void;
  onError?: (item: InstallQueueItem, err: unknown) => void;
}

const POLL_MS = 1000;
const TIMEOUT_MS = 90_000;

/** 从 pool 安装 409 响应的序列化错误文本中提取建议名。 */
function extractSuggestedName(err: unknown): string | undefined {
  if (!(err instanceof Error)) return undefined;
  const match = err.message.match(/"suggested_name"\s*:\s*"([^"]+)"/);
  return match?.[1] || undefined;
}

export function useMarketInstall(opts: UseMarketInstallOptions) {
  const [queue, setQueueState] = useState<InstallQueueItem[]>([]);
  const queueRef = useRef<InstallQueueItem[]>([]);
  const runningRef = useRef(false);
  const cancelledRef = useRef<Set<string>>(new Set());
  const currentTaskIdRef = useRef<string | null>(null);
  const currentInstallingItemIdRef = useRef<string | null>(null);
  const selectedAgentRef = useRef(opts.selectedAgent);
  useEffect(() => {
    selectedAgentRef.current = opts.selectedAgent;
  }, [opts.selectedAgent]);

  const setQueue = useCallback((next: InstallQueueItem[]) => {
    queueRef.current = next;
    setQueueState(next);
  }, []);

  const updateItem = useCallback(
    (id: string, patch: Partial<InstallQueueItem>) => {
      const next = queueRef.current.map((it) =>
        it.id === id ? { ...it, ...patch } : it,
      );
      setQueue(next);
    },
    [setQueue],
  );

  const installWorkspace = useCallback(
    async (item: InstallQueueItem, overrideName: string | undefined) => {
      const agentId = selectedAgentRef.current;
      const task = await api.startHubSkillInstall(
        {
          bundle_url: item.result.source_url,
          version: item.result.version || undefined,
          enable: true,
          target_name: overrideName,
        },
        agentId,
      );
      currentTaskIdRef.current = task.task_id;
      currentInstallingItemIdRef.current = item.id;
      const startedAt = Date.now();
      try {
        while (currentTaskIdRef.current === task.task_id) {
          if (cancelledRef.current.has(item.id)) {
            await api.cancelHubSkillInstall(task.task_id, agentId);
            updateItem(item.id, { status: "cancelled", message: "" });
            return;
          }
          const status = await api.getHubSkillInstallStatus(
            task.task_id,
            agentId,
          );
          if (status.status === "completed" && status.result?.installed) {
            const installedName = String(status.result.name || "");
            invalidateSkillCache({ agentId, workspaces: true });
            updateItem(item.id, {
              status: "completed",
              installedName,
              message: installedName,
            });
            notifySkillChange(agentId);
            opts.onSuccess?.({ ...item, status: "completed" });
            return;
          }
          if (status.status === "failed") {
            // 冲突失败：从任务结果提取建议名，供队列展示并支持
            // “用新名重试”，避免用户卡死在同名冲突上无路可走。
            const suggested = status.result?.conflicts?.find(
              (c) => c.suggested_name,
            )?.suggested_name;
            if (suggested) {
              updateItem(item.id, {
                status: "failed",
                suggestedName: suggested,
              });
              opts.onError?.(
                { ...item, status: "failed" },
                new Error(status.error || ""),
              );
              return;
            }
            // Throw with the server's message (already localized
            // upstream when possible). Empty string means installer
            // gave no detail — let the status tag stand alone.
            throw new Error(status.error || "");
          }
          if (status.status === "cancelled") {
            updateItem(item.id, { status: "cancelled", message: "" });
            return;
          }
          if (Date.now() - startedAt > TIMEOUT_MS) {
            await api.cancelHubSkillInstall(task.task_id, agentId);
            updateItem(item.id, {
              status: "failed",
              message: "__TIMED_OUT__",
            });
            return;
          }
          await new Promise((res) => window.setTimeout(res, POLL_MS));
        }
      } finally {
        if (currentTaskIdRef.current === task.task_id) {
          currentTaskIdRef.current = null;
        }
        if (currentInstallingItemIdRef.current === item.id) {
          currentInstallingItemIdRef.current = null;
        }
      }
    },
    [opts, updateItem],
  );

  const installOne = useCallback(
    async (item: InstallQueueItem, overrideName: string | undefined) => {
      updateItem(item.id, {
        status: "installing",
        message: "",
        suggestedName: undefined,
        retryName: undefined,
      });
      try {
        if (item.target === "pool") {
          currentInstallingItemIdRef.current = item.id;
          try {
            const result = await api.importPoolSkillFromHub({
              bundle_url: item.result.source_url,
              version: item.result.version || undefined,
              target_name: overrideName,
            });
            if (cancelledRef.current.has(item.id)) {
              updateItem(item.id, { status: "cancelled", message: "" });
              return;
            }
            // 员工技能页入口：入池后立即分发给来源员工；分发失败
            // 降级为部分成功提示，不回滚已入池的资产。
            let deliverFailed = false;
            if (item.deliverAgentId) {
              try {
                await api.downloadSkillPoolSkill({
                  skill_name: result.name,
                  targets: [{ workspace_id: item.deliverAgentId }],
                });
              } catch {
                deliverFailed = true;
              }
            }
            invalidateSkillCache({
              pool: true,
              ...(item.deliverAgentId
                ? { agentId: item.deliverAgentId, workspaces: true }
                : {}),
            });
            updateItem(item.id, {
              status: "completed",
              installedName: result.name,
              message: deliverFailed
                ? "__DELIVER_FAILED__"
                : result.name,
            });
            opts.onSuccess?.({ ...item, status: "completed" });
          } finally {
            if (currentInstallingItemIdRef.current === item.id) {
              currentInstallingItemIdRef.current = null;
            }
          }
        } else {
          await installWorkspace(item, overrideName);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        const suggested = extractSuggestedName(err);
        updateItem(item.id, {
          status: "failed",
          message: msg,
          ...(suggested ? { suggestedName: suggested } : {}),
        });
        opts.onError?.({ ...item, status: "failed" }, err);
      }
    },
    [installWorkspace, opts, updateItem],
  );

  const runQueue = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    try {
      while (true) {
        const next = queueRef.current.find((it) => it.status === "queued");
        if (!next) break;
        if (cancelledRef.current.has(next.id)) {
          // Status tag already says "cancelled"; no extra English label.
          updateItem(next.id, { status: "cancelled", message: "" });
          continue;
        }
        await installOne(next, next.retryName);
      }
    } finally {
      runningRef.current = false;
    }
  }, [installOne, updateItem]);

  const enqueue = useCallback(
    (results: MarketResult[], target: InstallTarget) => {
      const agentId = selectedAgentRef.current;
      const items: InstallQueueItem[] = results.map((r) => ({
        id: `${r.source}:${r.slug}:${Date.now()}:${Math.random()
          .toString(36)
          .slice(2, 7)}`,
        result: r,
        target,
        status: "queued",
        message: "",
        ...(target === "workspace" && agentId
          ? { targetAgentId: agentId }
          : {}),
        ...(target === "pool" && opts.deliverAgentId
          ? { deliverAgentId: opts.deliverAgentId }
          : {}),
      }));
      setQueue([...queueRef.current, ...items]);
      void runQueue();
      return items;
    },
    [opts.deliverAgentId, runQueue, setQueue],
  );

  const cancel = useCallback(
    (id: string) => {
      cancelledRef.current.add(id);
      if (id !== currentInstallingItemIdRef.current) {
        updateItem(id, { status: "cancelled", message: "" });
        return;
      }
      const taskId = currentTaskIdRef.current;
      if (taskId) {
        void api.cancelHubSkillInstall(taskId, selectedAgentRef.current);
      }
    },
    [updateItem],
  );

  const retry = useCallback(
    (id: string, overrideName?: string) => {
      if (!queueRef.current.some((it) => it.id === id)) return;
      cancelledRef.current.delete(id);
      updateItem(id, {
        status: "queued",
        message: "",
        retryName: overrideName,
      });
      void runQueue();
    },
    [runQueue, updateItem],
  );

  const clearFinished = useCallback(() => {
    setQueue(
      queueRef.current.filter(
        (it) => it.status === "queued" || it.status === "installing",
      ),
    );
  }, [setQueue]);

  return { queue, enqueue, cancel, retry, clearFinished };
}

export type MarketInstallController = ReturnType<typeof useMarketInstall>;
