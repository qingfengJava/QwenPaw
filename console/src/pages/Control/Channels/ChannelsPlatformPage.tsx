import { useEffect, useMemo, useState } from "react";
import { Card, Spin } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowRight } from "lucide-react";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import { AgentStatusIndicator } from "@/components/AgentStatusIndicator";
import { getAgentDisplayName } from "@/utils/agentDisplayName";
import { PageHeader } from "@/components/PageHeader";
import { ChannelIcon, getChannelLabel } from "./components";
import styles from "./platform.module.less";

interface AgentChannelRow {
  enabledChannels: string[];
}

/**
 * 平台级渠道接入页（平台 IA 阶段 5）：后端渠道接口按请求员工返回、
 * 无跨员工查询，这里对每个员工并行拉取后按员工分组聚合展示（只读）。
 * 点击员工卡进入详情页 `/agents/:aid/channels` 做绑定配置。
 */
export function ChannelsPlatformPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, refreshAgents } = useAgentStore();
  const [rows, setRows] = useState<Record<string, AgentChannelRow>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  // 以员工 id 签名为依赖，避免 refreshAgents 引用变化触发重复拉取
  const agentIdsKey = useMemo(
    () => agents.map((agent) => agent.id).join(","),
    [agents],
  );

  useEffect(() => {
    const current = useAgentStore.getState().agents;
    if (current.length === 0) return;
    let cancelled = false;
    setLoading(true);
    Promise.all(
      current.map(async (agent) => {
        try {
          const data = await api.listChannels(agent.id);
          const cfg = (data ?? {}) as unknown as Record<
            string,
            Record<string, unknown>
          >;
          const enabled = Object.keys(cfg).filter((k) => cfg[k]?.enabled);
          return [agent.id, { enabledChannels: enabled }] as const;
        } catch {
          // 单个员工拉取失败不阻断整体，展示为空
          return [agent.id, { enabledChannels: [] }] as const;
        }
      }),
    ).then((entries) => {
      if (!cancelled) {
        setRows(Object.fromEntries(entries));
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [agentIdsKey]);

  return (
    <div className={styles.channelWrap}>
      <PageHeader current={t("nav.channels", "Channels")} />
      <div className={styles.platformHint}>
        {t(
          "channels.platformHint",
          "Click an employee card to manage its channel bindings",
        )}
      </div>

      {loading ? (
        <div className={styles.loadingWrap}>
          <Spin />
        </div>
      ) : (
        <div className={styles.agentGrid}>
          {agents.map((agent) => {
            const row = rows[agent.id];
            const enabled = row?.enabledChannels ?? [];
            return (
              <Card
                key={agent.id}
                size="small"
                className={styles.agentCard}
                onClick={() => navigate(`/agents/${agent.id}/channels`)}
              >
                <div className={styles.agentHead}>
                  <AgentStatusIndicator
                    status={agent.startup_status}
                    enabled={agent.enabled}
                  />
                  <span className={styles.agentName}>
                    {getAgentDisplayName(agent, t)}
                  </span>
                  <ArrowRight size={14} className={styles.agentArrow} />
                </div>
                {enabled.length > 0 ? (
                  <div className={styles.channelChips}>
                    {enabled.map((key) => (
                      <span key={key} className={styles.chip}>
                        <ChannelIcon channelKey={key} size={14} />
                        {getChannelLabel(key, t)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className={styles.emptyText}>
                    {t(
                      "channels.platformEmpty",
                      "No channels enabled for this employee yet",
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

// lazyImportWithRetry 经 import.meta.glob 取 default 导出，必须有 default。
export default ChannelsPlatformPage;
