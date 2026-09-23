import { useState, useEffect, useCallback, useMemo } from "react";
import api from "../../../api";
import type { ChannelSchema } from "../../../api/modules/channel";
import { useAgentStore } from "../../../stores/agentStore";

/**
 * Channels data hook. `agentId`（可选）显式指定员工时优先（平台页逐员工拉取），
 * 否则沿用全局 selectedAgent（详情页借壳数据域）。
 */
export function useChannels(agentId?: string) {
  const { selectedAgent } = useAgentStore();
  const effectiveAgent = agentId ?? selectedAgent;
  const [channels, setChannels] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [channelTypes, setChannelTypes] = useState<string[]>([]);
  const [channelSchemas, setChannelSchemas] = useState<
    Record<string, ChannelSchema>
  >({});
  const [loading, setLoading] = useState(true);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    try {
      const [data, types] = await Promise.all([
        api.listChannels(agentId),
        api.listChannelTypes(),
      ]);
      if (data)
        setChannels(data as unknown as Record<string, Record<string, unknown>>);
      if (types) setChannelTypes(types);
    } catch (error) {
      console.error("❌ Failed to load channels:", error);
    } finally {
      setLoading(false);
    }
    // Fetch schemas separately so failures don't block core channel loading
    try {
      const schemas = await api.listChannelSchemas();
      if (schemas) setChannelSchemas(schemas);
    } catch {
      // Plugin system may not be available; non-critical
    }
  }, [agentId]);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels, effectiveAgent]);

  // Built-in channels come first (in a fixed order), then custom channels
  const builtinOrder = useMemo(
    () => [
      "console",
      "dingtalk",
      "feishu",
      "imessage",
      "discord",
      "telegram",
      "qq",
      "wechat",
      "wecom",
      "yuanbao",
      "matrix",
      "sip",
      "xiaoyi",
    ],
    [],
  );

  const orderedKeys = useMemo(
    () => [
      ...builtinOrder.filter((k) => channelTypes.includes(k)),
      ...channelTypes.filter((k) => !builtinOrder.includes(k)),
    ],
    [builtinOrder, channelTypes],
  );

  // Read isBuiltin from API response
  const isBuiltin = useCallback(
    (key: string) => Boolean(channels[key]?.isBuiltin),
    [channels],
  );

  return {
    channels,
    channelTypes,
    channelSchemas,
    orderedKeys,
    isBuiltin,
    loading,
    fetchChannels,
  };
}
