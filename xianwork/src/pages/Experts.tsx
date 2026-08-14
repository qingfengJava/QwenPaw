/**
 * Experts — published expert & expert-team catalog. Clicking a card
 * starts a chat with that expert (X-Agent-Id header on the console
 * chat plane).
 */
import { useCallback, useEffect, useState } from "react";
import { Segmented, message } from "antd";
import { chatApi, expertApi } from "../api/modules";
import type { Expert, ExpertTeam } from "../api/modules";
import { buildAgentRequest, streamChat } from "./Home";

export default function ExpertsPage() {
  const [view, setView] = useState<"experts" | "teams">("experts");
  const [experts, setExperts] = useState<Expert[]>([]);
  const [teams, setTeams] = useState<ExpertTeam[]>([]);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");

  const load = useCallback(async () => {
    try {
      const [e, t] = await Promise.all([
        expertApi.list(),
        expertApi.listTeams(),
      ]);
      setExperts(e);
      setTeams(t);
    } catch (err) {
      message.error(`加载专家失败：${String(err)}`);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const talkTo = async (agentId: string, prompt: string) => {
    if (busy) return;
    setBusy(true);
    setReply("");
    try {
      const chat = await chatApi.create(prompt.slice(0, 20));
      await streamChat(
        "/console/chat",
        buildAgentRequest(prompt, chat.id),
        (raw) => {
          try {
            const evt = JSON.parse(raw);
            const delta =
              evt?.choices?.[0]?.delta?.content ??
              evt?.delta ??
              evt?.content ??
              (typeof evt?.text === "string" ? evt.text : "");
            if (delta) {
              setReply((prev) => prev + delta);
            }
          } catch {
            /* keepalive */
          }
        },
        { "X-Agent-Id": agentId },
      );
    } catch (err) {
      setReply(`（专家连接失败：${String(err)}）`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="xian-page">
      <div className="xian-page-title">专家 · 技能 · 连接器</div>
      <div className="xian-page-sub">
        管理员发布的企业专家与专家团，点击即可直接对话
      </div>

      <Segmented
        options={[
          { label: `专家（${experts.length}）`, value: "experts" },
          { label: `专家团（${teams.length}）`, value: "teams" },
        ]}
        value={view}
        onChange={(v) => setView(v as "experts" | "teams")}
        style={{ marginBottom: 20 }}
      />

      {reply && (
        <div
          style={{
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 10,
            padding: "12px 16px",
            marginBottom: 18,
            fontSize: 13,
            whiteSpace: "pre-wrap",
            maxHeight: 220,
            overflowY: "auto",
          }}
        >
          🤖 {reply}{busy ? "▍" : ""}
        </div>
      )}

      <div className="xian-card-grid">
        {view === "experts" &&
          experts.map((expert) => (
            <div
              key={expert.id}
              className="xian-card"
              onClick={() =>
                talkTo(expert.agent_id, `你好，请介绍一下你的专业能力。`)
              }
            >
              <div className="xian-card-title">
                {expert.icon || "🧠"} {expert.name}
              </div>
              <div className="xian-card-desc">
                {expert.description || "企业专家"}
                <div style={{ marginTop: 6, color: "var(--accent)" }}>
                  v{expert.version} · 点击对话
                </div>
              </div>
            </div>
          ))}
        {view === "teams" &&
          teams.map((team) => (
            <div
              key={team.id}
              className="xian-card"
              onClick={() =>
                talkTo(team.agent_id, `你好，请按${team.mode}模式协作处理我的请求。`)
              }
            >
              <div className="xian-card-title">👥 {team.name}</div>
              <div className="xian-card-desc">
                {team.description || "专家团"}
                <div style={{ marginTop: 6, color: "var(--accent)" }}>
                  {team.mode} · {team.member_count} 位成员 · 点击对话
                </div>
              </div>
            </div>
          ))}
        {view === "experts" && experts.length === 0 && (
          <div className="xian-card-desc">
            暂无已发布专家，请联系管理员在后台发布
          </div>
        )}
        {view === "teams" && teams.length === 0 && (
          <div className="xian-card-desc">暂无已发布专家团</div>
        )}
      </div>
    </div>
  );
}
