/**
 * Projects — "my projects" card grid + template gallery (WorkBuddy
 * style). Creating from a template copies the template project.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Modal, message } from "antd";
import { projectApi } from "../api/modules";
import type { Project } from "../api/modules";

const FALLBACK_TEMPLATES = [
  { tag: "prd-flow", name: "产品需求全流程", desc: "从需求规划、PRD 到研发测试验收" },
  { tag: "market-research", name: "市场调研与竞品分析", desc: "深度调研、竞品拆解、报告评审" },
  { tag: "team-kb", name: "团队知识库", desc: "持续沉淀 SOP、经验和 FAQ" },
  { tag: "delivery", name: "项目交付", desc: "管理客户需求、计划、风险和周报" },
  { tag: "bug-tracking", name: "Bug 跟踪 / 测试验收", desc: "持续跟踪 bug，统一测试用例与验收" },
];

export default function ProjectsPage() {
  const navigate = useNavigate();
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
      setProjects(all);
      setTemplates(tpl);
    } catch (err) {
      message.error(`加载项目失败：${String(err)}`);
    }
  }, []);

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
      message.success("项目已创建");
      setCreating(false);
      setName("");
      setDescription("");
      navigate(`/projects/${project.id}`);
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleFromTemplate = async (tag: string) => {
    try {
      const project = await projectApi.createFromTemplate(tag);
      navigate(`/projects/${project.id}`);
    } catch {
      message.info("该模板尚未由管理员发布，敬请期待");
    }
  };

  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(keyword.toLowerCase()),
  );

  return (
    <div className="xian-page">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 28,
        }}
      >
        <div>
          <div className="xian-page-title">项目</div>
          <div className="xian-page-sub">多人协同，打造超级团队</div>
          <Button
            type="primary"
            onClick={() => setCreating(true)}
            style={{ marginTop: 8 }}
          >
            ＋ 新建项目
          </Button>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <h3 style={{ fontSize: 15 }}>我的项目</h3>
        <Input
          placeholder="搜索项目"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 220 }}
          allowClear
        />
      </div>
      <div className="xian-card-grid" style={{ marginBottom: 36 }}>
        {filtered.map((project) => (
          <div
            key={project.id}
            className="xian-card"
            onClick={() => navigate(`/projects/${project.id}`)}
          >
            <div className="xian-card-title">🗂 {project.name}</div>
            <div className="xian-card-desc">
              {project.description || "暂无描述"}
              {project.member_role && (
                <span style={{ color: "var(--accent)" }}>
                  {" "}
                  · {project.member_role}
                </span>
              )}
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="xian-card-desc">还没有项目，从下方模板开始吧</div>
        )}
      </div>

      <h3 style={{ fontSize: 15, marginBottom: 14 }}>从模板创建</h3>
      <div className="xian-card-grid">
        {(templates.length
          ? templates.map((t) => ({
              tag: t.template_tag,
              name: t.name,
              desc: t.description,
            }))
          : FALLBACK_TEMPLATES
        ).map((tpl) => (
          <div
            key={tpl.tag}
            className="xian-card"
            onClick={() => handleFromTemplate(tpl.tag)}
          >
            <div className="xian-card-title">🧩 {tpl.name}</div>
            <div className="xian-card-desc">{tpl.desc}</div>
          </div>
        ))}
      </div>

      <Modal
        title="新建项目"
        open={creating}
        onOk={handleCreate}
        onCancel={() => setCreating(false)}
        destroyOnHidden
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Input
            placeholder="项目名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Input.TextArea
            placeholder="项目描述（可选）"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
      </Modal>
    </div>
  );
}
