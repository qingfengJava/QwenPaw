/**
 * ExpertFormModal — create / edit a personal expert: name, title,
 * category, visibility, tags, description, persona prompt, and the
 * skill multi-select (max 8, source: shared skill registry). Creating
 * publishes immediately (backend contract); editing re-publishes.
 */
import { useEffect, useState } from "react";
import Modal from "../Modal";
import { expertApi } from "../../api/modules";
import type {
  ExpertCategory,
  ExpertDetail,
  SkillView,
} from "../../api/modules";

export interface ExpertFormModalProps {
  open: boolean;
  /** Null = create; otherwise edit this expert. */
  editing: ExpertDetail | null;
  categories: ExpertCategory[];
  skills: SkillView[];
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}

interface FormState {
  name: string;
  title: string;
  category: string;
  visibility: "org" | "private";
  tags: string;
  description: string;
  system_prompt: string;
}

const EMPTY: FormState = {
  name: "",
  title: "",
  category: "general",
  visibility: "org",
  tags: "",
  description: "",
  system_prompt: "",
};

export default function ExpertFormModal({
  open,
  editing,
  categories,
  skills,
  onClose,
  onSaved,
  onError,
}: ExpertFormModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (editing) {
      setForm({
        name: editing.name,
        title: editing.title ?? "",
        category: editing.category ?? "general",
        visibility: (editing.visibility as "org" | "private") ?? "org",
        tags: (editing.tags ?? []).join("，"),
        description: editing.description ?? "",
        system_prompt: editing.system_prompt ?? "",
      });
      setPicked(
        (editing.skills ?? []).filter((s) => s.enabled).map((s) => s.skill_name),
      );
    } else {
      setForm(EMPTY);
      setPicked([]);
    }
  }, [open, editing]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const toggleSkill = (name: string) => {
    setPicked((prev) => {
      if (prev.includes(name)) {
        return prev.filter((n) => n !== name);
      }
      if (prev.length >= 8) {
        return prev;
      }
      return [...prev, name];
    });
  };

  const submit = async () => {
    if (!form.name.trim()) {
      onError("请填写专家名称");
      return;
    }
    setBusy(true);
    try {
      const tags = form.tags
        .split(/[,，\s]+/)
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 6);
      const skillBindings = picked.map((skill_name, seq) => ({
        skill_name,
        enabled: true,
        seq,
      }));
      if (editing) {
        await expertApi.update(editing.id, {
          name: form.name.trim(),
          title: form.title.trim(),
          category: form.category,
          visibility: form.visibility,
          tags,
          description: form.description.trim(),
          system_prompt: form.system_prompt.trim(),
        });
        await expertApi.setSkills(editing.id, skillBindings);
      } else {
        await expertApi.create({
          name: form.name.trim(),
          title: form.title.trim(),
          category: form.category,
          visibility: form.visibility,
          tags,
          description: form.description.trim(),
          system_prompt: form.system_prompt.trim(),
          skills: skillBindings,
        });
      }
      onSaved();
    } catch (err) {
      onError(`保存专家失败：${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={editing ? "编辑专家" : "创建专家"}
      onClose={onClose}
      width={560}
      footer={
        <button
          type="button"
          className="btn-black"
          disabled={busy}
          onClick={() => void submit()}
        >
          <i className="fa-solid fa-check" />
          {busy ? "保存中…" : editing ? "保存并重新发布" : "创建并发布"}
        </button>
      }
    >
      <div className="form-field">
        <label htmlFor="expert-form-name">名称 *</label>
        <input
          id="expert-form-name"
          value={form.name}
          maxLength={40}
          onChange={(e) => set("name", e.target.value)}
          placeholder="如：合同审查专家"
        />
      </div>
      <div className="expert-form-row">
        <div className="form-field">
          <label htmlFor="expert-form-title">职称</label>
          <input
            id="expert-form-title"
            value={form.title}
            maxLength={30}
            onChange={(e) => set("title", e.target.value)}
            placeholder="如：高级法务专家"
          />
        </div>
        <div className="form-field">
          <label htmlFor="expert-form-category">分类</label>
          <select
            id="expert-form-category"
            className="native-select"
            value={form.category}
            onChange={(e) => set("category", e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="expert-form-row">
        <div className="form-field">
          <label htmlFor="expert-form-visibility">可见范围</label>
          <select
            id="expert-form-visibility"
            className="native-select"
            value={form.visibility}
            onChange={(e) =>
              set("visibility", e.target.value as "org" | "private")
            }
          >
            <option value="org">全员可见</option>
            <option value="private">仅自己可见</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="expert-form-tags">标签（逗号分隔，最多 6 个）</label>
          <input
            id="expert-form-tags"
            value={form.tags}
            maxLength={80}
            onChange={(e) => set("tags", e.target.value)}
            placeholder="如：合同审查，风险提示"
          />
        </div>
      </div>
      <div className="form-field">
        <label htmlFor="expert-form-desc">简介</label>
        <textarea
          id="expert-form-desc"
          value={form.description}
          maxLength={200}
          onChange={(e) => set("description", e.target.value)}
          placeholder="一两句话说清这位专家解决什么问题"
        />
      </div>
      <div className="form-field">
        <label htmlFor="expert-form-prompt">领域人设（ReAct 工作法提示词）</label>
        <textarea
          id="expert-form-prompt"
          value={form.system_prompt}
          maxLength={1000}
          onChange={(e) => set("system_prompt", e.target.value)}
          placeholder={
            "描述这位专家的身份、专业领域与工作习惯；发布后与内置 ReAct 工作法（理解→规划→决策→生成→核验→偏差再规划）一起注入专家人格。"
          }
        />
      </div>
      <div className="form-field">
        <label>
          配置技能（对话时自动加载，已选 {picked.length}/8）
        </label>
        {skills.length > 0 ? (
          <div className="expert-tags expert-skill-picker">
            {skills.map((skill) => {
              const active = picked.includes(skill.name);
              return (
                <button
                  key={skill.name}
                  type="button"
                  className={`expert-tag expert-tag-option${active ? " active" : ""}`}
                  title={skill.description}
                  onClick={() => toggleSkill(skill.name)}
                >
                  {skill.name}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="expert-detail-hint">
            共享技能库暂无可用技能，可先创建专家，稍后在编辑中配置
          </p>
        )}
      </div>
    </Modal>
  );
}
