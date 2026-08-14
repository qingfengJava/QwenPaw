/**
 * Experts —「专家·技能·连接器」: published expert / expert-team catalog
 * plus the shared skill & connector lists (resource API). Clicking an
 * expert card starts a chat with it (X-Agent-Id on the console plane;
 * logic preserved, helpers from lib/stream.ts).
 */
import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import ProjectCard from "../components/ProjectCard";
import { useToast } from "../components/Toast";
import { chatApi, expertApi, resourceApi } from "../api/modules";
import type {
  ConnectorView,
  Expert,
  ExpertTeam,
  SkillView,
} from "../api/modules";
import { buildAgentRequest, streamChat } from "../lib/stream";

type View = "experts" | "teams" | "skills" | "connectors";

const VIEWS: { key: View; label: string }[] = [
  { key: "experts", label: "专家" },
  { key: "teams", label: "专家团" },
  { key: "skills", label: "技能" },
  { key: "connectors", label: "连接器" },
];

export default function ExpertsPage() {
  const toast = useToast();
  const [view, setView] = useState<View>("experts");
  const [experts, setExperts] = useState<Expert[]>([]);
  const [teams, setTeams] = useState<ExpertTeam[]>([]);
  const [skills, setSkills] = useState<SkillView[]>([]);
  const [connectors, setConnectors] = useState<ConnectorView[]>([]);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");

  const load = useCallback(async () => {
    try {
      const [e, t, s, c] = await Promise.all([
        expertApi.list(),
        expertApi.listTeams(),
        resourceApi.skills().catch(() => []),
        resourceApi.connectors().catch(() => []),
      ]);
      setExperts(e);
      setTeams(t);
      setSkills(s);
      setConnectors(c);
    } catch (err) {
      toast.error(`加载专家失败：${String(err)}`);
    }
  }, [toast]);

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
        (raw: string) => {
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
    <div className="view active">
      <PageShell
        title="专家 · 技能 · 连接器"
        subtitle="管理员发布的企业专家与专家团，点击即可直接对话；技能与连接器可在项目中绑定使用"
      >
        <div
          className="filter-toggle"
          style={{ display: "inline-flex", marginBottom: 20 }}
        >
          {VIEWS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`filter-option${view === item.key ? " active" : ""}`}
              onClick={() => setView(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {reply && (
          <div className="chat-stream-box" style={{ maxWidth: 820, marginBottom: 18 }}>
            <i
              className="fa-solid fa-robot"
              style={{ color: "#94a3b8", marginRight: 6 }}
            />
            {reply}
            {busy ? "▍" : ""}
          </div>
        )}

        {view === "experts" && (
          <div className="card-grid">
            {experts.map((expert) => (
              <ProjectCard
                key={expert.id}
                icon="fa-solid fa-user-tie"
                title={expert.name}
                desc={`${expert.description || "企业专家"}\nv${expert.version} · 点击对话`}
                onClick={() =>
                  void talkTo(expert.agent_id, "你好，请介绍一下你的专业能力。")
                }
              />
            ))}
            {experts.length === 0 && (
              <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                暂无已发布专家，请联系管理员在后台发布
              </div>
            )}
          </div>
        )}

        {view === "teams" && (
          <div className="card-grid">
            {teams.map((team) => (
              <ProjectCard
                key={team.id}
                icon="fa-solid fa-users-rectangle"
                title={team.name}
                desc={`${team.description || "专家团"}\n${team.mode} · ${team.member_count} 位成员 · 点击对话`}
                onClick={() =>
                  void talkTo(
                    team.agent_id,
                    `你好，请按${team.mode}模式协作处理我的请求。`,
                  )
                }
              />
            ))}
            {teams.length === 0 && (
              <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                暂无已发布专家团
              </div>
            )}
          </div>
        )}

        {view === "skills" && (
          <div className="card-grid">
            {skills.map((skill) => (
              <ProjectCard
                key={skill.name}
                template
                icon="fa-solid fa-bolt"
                title={skill.name}
                desc={skill.description || "工作区技能"}
              />
            ))}
            {skills.length === 0 && (
              <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                工作区暂无已安装技能
              </div>
            )}
          </div>
        )}

        {view === "connectors" && (
          <div className="card-grid">
            {connectors.map((connector) => (
              <ProjectCard
                key={connector.client_key}
                template
                icon="fa-solid fa-plug"
                title={connector.display_name}
                desc={`${connector.transport || "MCP"}${connector.enabled ? "" : " · 已停用"}${connector.description ? ` · ${connector.description}` : ""}`}
              />
            ))}
            {connectors.length === 0 && (
              <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                管理员尚未配置 MCP 连接器
              </div>
            )}
          </div>
        )}
      </PageShell>
    </div>
  );
}
