/**
 * WavePreview — live topological layering of a DAG node template.
 *
 * Feeds the admin team editor's standard/fast chain JSON textareas: as
 * the admin types, the component parses the nodes, layers them into
 * execution waves (the same minimal Kahn pass the backend engine runs)
 * and renders one chip row per wave — same-wave multi-node rows are
 * badged 并行, making parallel member execution (fe ∥ be) visible at
 * a glance instead of hidden inside deps arrays.
 */
import { useMemo } from "react";
import { Empty, Tag, Typography } from "antd";

export interface PreviewNode {
  node_key: string;
  deps?: string[];
  node_type?: string;
}

/**
 * Layer node keys into execution waves (mirror of the backend
 * `topological_waves` / xianwork RunDetail `waveKeys`): a node enters
 * the next wave once every dep is placed. Unresolvable keys (cycles /
 * unknown deps) are dropped from waves and reported back.
 */
export function waveLayering(nodes: PreviewNode[]): {
  waves: string[][];
  unresolved: string[];
} {
  const byKey = new Map(nodes.map((n) => [n.node_key, n]));
  const placed = new Set<string>();
  const waves: string[][] = [];
  const resolved = new Set<string>();
  let remaining = nodes.map((n) => n.node_key);
  while (remaining.length > 0) {
    const ready = remaining.filter((key) =>
      (byKey.get(key)?.deps ?? []).every((dep) => placed.has(dep)),
    );
    if (ready.length === 0) {
      break;
    }
    // Deterministic order within a wave: follow the input order.
    const wave = remaining.filter((k) => ready.includes(k));
    for (const key of wave) {
      placed.add(key);
      resolved.add(key);
    }
    waves.push(wave);
    remaining = remaining.filter((k) => !ready.includes(k));
  }
  return { waves, unresolved: remaining.filter((k) => !resolved.has(k)) };
}

function parseNodes(json: string | undefined): PreviewNode[] | null {
  const text = (json ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter(
      (n): n is PreviewNode =>
        !!n && typeof n === "object" && typeof n.node_key === "string",
    );
  } catch {
    return null;
  }
}

export default function WavePreview({
  nodesJson,
  emptyHint = "尚未配置节点",
}: {
  /** The editor's raw JSON text (parsed defensively). */
  nodesJson: string | undefined;
  emptyHint?: string;
}) {
  const result = useMemo(() => {
    const nodes = parseNodes(nodesJson);
    if (nodes === null) return { error: true } as const;
    if (nodes.length === 0) return { error: false, waves: [] as string[][], unresolved: [] as string[] };
    const { waves, unresolved } = waveLayering(nodes);
    return { error: false, waves, unresolved };
  }, [nodesJson]);

  if (result.error) {
    return (
      <Typography.Text type="danger" style={{ fontSize: 12 }}>
        JSON 无法解析，波次预览不可用
      </Typography.Text>
    );
  }
  // 全部节点无法分层（环/未知依赖）→ 报错而非空态（否则环被静默吞掉）
  if (result.waves.length === 0 && result.unresolved.length > 0) {
    return (
      <Typography.Text type="danger" style={{ fontSize: 12 }}>
        无法分层（环或未知依赖）：{result.unresolved.join("、")}
      </Typography.Text>
    );
  }
  if (result.waves.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyHint} />;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {result.waves.map((wave, idx) => (
        <div key={idx} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, width: 88 }}>
            第 {idx + 1} 波
          </Typography.Text>
          {wave.map((key) => (
            <Tag key={key} color={wave.length > 1 ? "geekblue" : "default"}>
              {key}
            </Tag>
          ))}
          {wave.length > 1 && (
            <Tag color="processing" style={{ marginLeft: 0 }}>
              并行
            </Tag>
          )}
        </div>
      ))}
      {result.unresolved.length > 0 && (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          无法分层（环或未知依赖）：{result.unresolved.join("、")}
        </Typography.Text>
      )}
    </div>
  );
}
