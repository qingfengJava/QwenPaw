/**
 * Projects — prototype projects view (L1143-1210): header with btn-black
 * create, embedded-icon search box, "my projects" card grid, template
 * gallery. Data flow preserved (list / create / from-template).
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal from "../components/Modal";
import ProjectCard from "../components/ProjectCard";
import { useToast } from "../components/Toast";
import { projectApi } from "../api/modules";
import type { Project } from "../api/modules";

const FALLBACK_TEMPLATES = [
  { tag: "prd-flow", name: "产品需求全流程", desc: "从需求规划、PRD 到研发测试验收", icon: "fa-solid fa-cube" },
  { tag: "market-research", name: "市场调研与竞品分析", desc: "深度调研、竞品拆解、报告评审", icon: "fa-solid fa-chart-line" },
  { tag: "team-kb", name: "团队知识库", desc: "持续沉淀 SOP、经验和 FAQ", icon: "fa-solid fa-book-open" },
  { tag: "delivery", name: "项目交付", desc: "管理客户需求、计划、风险和周报", icon: "fa-solid fa-truck-fast" },
  { tag: "bug-tracking", name: "Bug 跟踪 / 测试验收", desc: "持续跟踪 bug，统一测试用例和验收结论", icon: "fa-solid fa-bug" },
];

const MY_PROJECT_ICONS = [
  "fa-solid fa-rocket",
  "fa-solid fa-layer-group",
  "fa-solid fa-lightbulb",
  "fa-solid fa-diagram-project",
];

export default function ProjectsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [projects, setProjects] = useState<Project[]>([]);
  const [templates, setTemplates] = useState<Project[]>([]);
  const [keyword, setKeyword] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(async () => {
    try {
      const [all, tpl] = await Promise.all([
        projectApi.list(),
        projectApi.list(true).catch(() => [] as Project[]),
      ]);
      setProjects(all.filter((p) => !p.template_tag));
      setTemplates(tpl);
    } catch (err) {
      toast.error(`加载项目失败：${String(err)}`);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const project = await projectApi.create({
        name: name.trim(),
        description: description.trim(),
      });
      toast.success("项目已创建");
      setCreating(false);
      setName("");
      setDescription("");
      navigate(`/projects/${project.id}`);
    } catch (err) {
      toast.error(String(err));
    }
  };

  const handleFromTemplate = async (tag: string) => {
    try {
      const project = await projectApi.createFromTemplate(tag);
      navigate(`/projects/${project.id}`);
    } catch {
      toast.info("该模板尚未由管理员发布，敬请期待");
    }
  };

  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(keyword.toLowerCase()),
  );

  return (
    <div className="view active">
      <div className="projects-layout">
        <div className="projects-header-area">
          <div className="projects-header-left">
            <h1>项目</h1>
            <p>多人协同，打造超级团队</p>
            <button
              type="button"
              className="btn-black"
              onClick={() => setCreating(true)}
            >
              <i className="fa-solid fa-plus" /> 新建项目
            </button>
          </div>
          <div style={{ fontSize: 60, color: "#e2e8f0" }}>
            <i className="fa-solid fa-users-viewfinder" />
          </div>
        </div>

        <div className="section-heading">
          <h3>我的项目</h3>
          <div className="search-input-box">
            <i className="fa-solid fa-magnifying-glass" />
            <input
              type="text"
              placeholder="搜索项目"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
        </div>

        <div
          className="card-grid"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}
        >
          {filtered.map((project, index) => (
            <ProjectCard
              key={project.id}
              icon={MY_PROJECT_ICONS[index % MY_PROJECT_ICONS.length]}
              title={project.name}
              desc={
                project.description ||
                `添加于 ${project.created_at?.slice(0, 10) ?? "刚刚"}`
              }
              onClick={() => navigate(`/projects/${project.id}`)}
              onMore={() => navigate(`/projects/${project.id}`)}
            />
          ))}
          {filtered.length === 0 && (
            <div className="card-desc" style={{ gridColumn: "1 / -1" }}>
              还没有项目，从下方模板开始吧
            </div>
          )}
        </div>

        <div className="section-heading" style={{ marginTop: 20 }}>
          <h3>从模版创建</h3>
        </div>

        <div className="card-grid">
          {(templates.length
            ? templates.map((t) => ({
                tag: t.template_tag,
                name: t.name,
                desc: t.description,
                icon:
                  FALLBACK_TEMPLATES.find((f) => f.tag === t.template_tag)
                    ?.icon ?? "fa-solid fa-cube",
              }))
            : FALLBACK_TEMPLATES
          ).map((tpl) => (
            <ProjectCard
              key={tpl.tag}
              template
              icon={tpl.icon}
              title={tpl.name}
              desc={tpl.desc}
              onClick={() => void handleFromTemplate(tpl.tag)}
            />
          ))}
        </div>
      </div>

      <Modal
        open={creating}
        title="新建项目"
        onClose={() => setCreating(false)}
        footer={
          <>
            <button
              type="button"
              className="btn-plain"
              onClick={() => setCreating(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-black"
              onClick={() => void handleCreate()}
            >
              创建
            </button>
          </>
        }
      >
        <div className="form-field">
          <label>项目名称</label>
          <input
            placeholder="给项目起个名字"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                void handleCreate();
              }
            }}
          />
        </div>
        <div className="form-field">
          <label>项目描述（可选）</label>
          <textarea
            placeholder="这个项目要做什么？"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
      </Modal>
    </div>
  );
}
