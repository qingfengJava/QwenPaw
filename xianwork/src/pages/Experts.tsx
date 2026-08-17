/**
 * Experts —「专家·技能·连接器」market page.
 *
 * Experts tab: search + category chips + sort (综合/最热/最新) +
 * all/mine scope + WorkBuddy-style cards; summon jumps to the Chat
 * page with the expert's agent preselected (X-Agent-Id flows from
 * chatPrefs) and a kickoff message — the full chat experience
 * (approval / loop modes / model picker) replaces the old inline
 * mini-chat. Teams tab: team cards → detail modal (member roster +
 * 主理人 badges + 召唤专家团). Skills/connectors tabs unchanged.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageShell from "../components/PageShell";
import ProjectCard from "../components/ProjectCard";
import { useToast } from "../components/Toast";
import ExpertCard from "../components/experts/ExpertCard";
import TeamCard from "../components/experts/TeamCard";
import ExpertDetailModal from "../components/experts/ExpertDetailModal";
import TeamDetailModal from "../components/experts/TeamDetailModal";
import ExpertFormModal from "../components/experts/ExpertFormModal";
import { teamModeLabel } from "../components/experts/TeamCard";
import { chatApi, expertApi, resourceApi } from "../api/modules";
import type {
  ConnectorView,
  Expert,
  ExpertCategory,
  ExpertDetail,
  ExpertTeam,
  SkillView,
} from "../api/modules";
import { useAuthStore } from "../stores/auth";
import { useChatPrefs } from "../stores/chatPrefs";
import { useChatsStore } from "../stores/chats";

type View = "experts" | "teams" | "skills" | "connectors";
type Sort = "composite" | "hot" | "new";
type Scope = "all" | "mine";

const VIEWS: { key: View; label: string }[] = [
  { key: "experts", label: "专家" },
  { key: "teams", label: "专家团" },
  { key: "skills", label: "技能" },
  { key: "connectors", label: "连接器" },
];

const SORTS: { key: Sort; label: string }[] = [
  { key: "composite", label: "综合" },
  { key: "hot", label: "最热" },
  { key: "new", label: "最新" },
];

const KICKOFF_EXPERT = "你好，请介绍一下你的专业能力。";

export default function ExpertsPage() {
  const toast = useToast();
  const navigate = useNavigate();

  const [view, setView] = useState<View>("experts");
  const [scope, setScope] = useState<Scope>("all");
  const [sort, setSort] = useState<Sort>("composite");
  const [category, setCategory] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchText, setSearchText] = useState("");

  const [experts, setExperts] = useState<Expert[]>([]);
  const [teams, setTeams] = useState<ExpertTeam[]>([]);
  const [skills, setSkills] = useState<SkillView[]>([]);
  const [connectors, setConnectors] = useState<ConnectorView[]>([]);
  const [categories, setCategories] = useState<ExpertCategory[]>([]);
  const [summoning, setSummoning] = useState(false);

  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailTeam, setDetailTeam] = useState<ExpertTeam | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ExpertDetail | null>(null);

  const debounceRef = useRef<number | null>(null);

  /** Search box → keyword with a 300ms debounce (avoids per-keystroke fetches). */
  const onSearchInput = (value: string) => {
    setSearchText(value);
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      setKeyword(value.trim());
    }, 300);
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const loadExperts = useCallback(async () => {
    try {
      const params = { category, q: keyword, sort };
      const list = scope === "mine" ? await expertApi.mine(params) : await expertApi.list(params);
      setExperts(list);
    } catch (err) {
      toast.error(`加载专家失败：${String(err)}`);
    }
  }, [category, keyword, sort, scope, toast]);

  const loadTeams = useCallback(async () => {
    try {
      setTeams(await expertApi.listTeams());
    } catch (err) {
      toast.error(`加载专家团失败：${String(err)}`);
    }
  }, [toast]);

  const loadResources = useCallback(async () => {
    const [s, c, cats] = await Promise.all([
      resourceApi.skills().catch(() => []),
      resourceApi.connectors().catch(() => []),
      expertApi.categories().catch(() => []),
    ]);
    setSkills(s);
    setConnectors(c);
    setCategories(cats);
  }, []);

  useEffect(() => {
    void loadExperts();
  }, [loadExperts]);

  useEffect(() => {
    if (view === "teams") {
      void loadTeams();
    }
  }, [view, loadTeams]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  /**
   * Summon: mark usage, pin the expert's agent in chatPrefs (drives
   * the X-Agent-Id header), create a fresh chat and hand off to the
   * Chat page with a kickoff message — full chat surface, no inline
   * mini-chat duplication.
   */
  const summon = useCallback(
    async (agentId: string, chatName: string, kickoff: string) => {
      if (summoning) {
        return;
      }
      setSummoning(true);
      try {
        useChatPrefs.getState().setSelectedAgent(agentId);
        const username = useAuthStore.getState().username;
        const chat = await chatApi.create(chatName.slice(0, 30), username);
        await useChatsStore.getState().reload();
        navigate(
          `/chat?chat=${encodeURIComponent(chat.id)}&kickoff=${encodeURIComponent(kickoff)}`,
        );
      } catch (err) {
        toast.error(`发起会话失败：${String(err)}`);
        setSummoning(false);
      }
    },
    [navigate, summoning, toast],
  );

  const summonExpert = useCallback(
    (expert: { id: string; name: string; agent_id: string }) => {
      void expertApi.use(expert.id).catch(() => undefined);
      setDetailId(null);
      setDetailTeam(null);
      void summon(
        expert.agent_id,
        `专家对话 · ${expert.name}`,
        KICKOFF_EXPERT,
      );
    },
    [summon],
  );

  const summonTeam = useCallback(
    (team: ExpertTeam) => {
      setDetailTeam(null);
      void summon(
        team.agent_id,
        `专家团 · ${team.name}`,
        `你好，请按${teamModeLabel(team.mode)}的方式协作处理我的请求。`,
      );
    },
    [summon],
  );

  const openEdit = useCallback(async (expert: Expert) => {
    try {
      setEditing(await expertApi.detail(expert.id));
      setFormOpen(true);
    } catch (err) {
      setEditing(null);
      setFormOpen(true);
    }
  }, []);

  const removeExpert = useCallback(
    async (expert: Expert) => {
      if (!window.confirm(`确定删除专家「${expert.name}」吗？已发布专家将归档。`)) {
        return;
      }
      try {
        await expertApi.remove(expert.id);
        toast.success("已删除");
        void loadExperts();
      } catch (err) {
        toast.error(`删除失败：${String(err)}`);
      }
    },
    [loadExperts, toast],
  );

  const onFormSaved = useCallback(() => {
    setFormOpen(false);
    setEditing(null);
    toast.success("已保存并发布");
    void loadExperts();
  }, [loadExperts, toast]);

  return (
    <div className="view active">
      <PageShell
        title="专家 · 技能 · 连接器"
        subtitle="召唤企业专家与专家团开始对话，技能在对话中自动加载；也可创建自己的专属专家"
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

        {view === "experts" && (
          <>
            <div className="expert-toolbar">
              <div className="search-input-box">
                <i className="fa-solid fa-magnifying-glass" />
                <input
                  value={searchText}
                  placeholder="搜索专家职称、名称或描述"
                  onChange={(e) => onSearchInput(e.target.value)}
                />
              </div>
              <div className="filter-toggle" style={{ display: "inline-flex" }}>
                <button
                  type="button"
                  className={`filter-option${scope === "all" ? " active" : ""}`}
                  onClick={() => setScope("all")}
                >
                  全部专家
                </button>
                <button
                  type="button"
                  className={`filter-option${scope === "mine" ? " active" : ""}`}
                  onClick={() => setScope("mine")}
                >
                  我的专家
                </button>
              </div>
              <div className="filter-toggle" style={{ display: "inline-flex" }}>
                {SORTS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={`filter-option${sort === item.key ? " active" : ""}`}
                    onClick={() => setSort(item.key)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="btn-black"
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                <i className="fa-solid fa-plus" />
                创建专家
              </button>
            </div>

            <div className="filter-toggle expert-category-bar">
              <button
                type="button"
                className={`filter-option${category === "" ? " active" : ""}`}
                onClick={() => setCategory("")}
              >
                全部
              </button>
              {categories.map((cat) => (
                <button
                  key={cat.key}
                  type="button"
                  className={`filter-option${category === cat.key ? " active" : ""}`}
                  onClick={() => setCategory(cat.key)}
                >
                  <i className={cat.icon} style={{ marginRight: 6 }} />
                  {cat.label}
                </button>
              ))}
            </div>

            <div className="card-grid">
              {experts.map((expert) => (
                <ExpertCard
                  key={expert.id}
                  expert={expert}
                  mine={scope === "mine"}
                  onSummon={summonExpert}
                  onDetail={(e) => setDetailId(e.id)}
                  onEdit={(e) => void openEdit(e)}
                  onDelete={(e) => void removeExpert(e)}
                />
              ))}
              {experts.length === 0 && (
                <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                  {scope === "mine"
                    ? "你还没有自定义专家，点击右上角「创建专家」新建一个"
                    : "暂无可见专家，可切换「我的专家」或联系管理员发布"}
                </div>
              )}
            </div>
          </>
        )}

        {view === "teams" && (
          <div className="card-grid">
            {teams.map((team) => (
              <TeamCard key={team.id} team={team} onOpen={setDetailTeam} />
            ))}
            {teams.length === 0 && (
              <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
                暂无已发布专家团，请联系管理员在后台组建并发布
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

      <ExpertDetailModal
        expertId={detailId}
        onClose={() => setDetailId(null)}
        onSummon={summonExpert}
      />
      <TeamDetailModal
        team={detailTeam}
        onClose={() => setDetailTeam(null)}
        onSummon={summonTeam}
      />
      <ExpertFormModal
        open={formOpen}
        editing={editing}
        categories={categories}
        skills={skills}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={onFormSaved}
        onError={(message) => toast.error(message)}
      />
    </div>
  );
}
