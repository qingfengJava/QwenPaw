/**
 * OperationsFields — admin editors for the marketplace operations
 * payload of experts / expert teams:
 *
 * - SampleTasksEditor: the "专家帮你做" template list [{title, prompt}]
 *   (one click on the detail page launches the expert with the prompt
 *   as kickoff / the team run with it as goal);
 * - ShowcaseEditor: the curated use-case cards [{title, desc, tags}]
 *   (static operations content; expert-team details additionally
 *   project real "最近交付" runs).
 *
 * Both mount as Form.List children inside the host antd Form, so the
 * values flow through the normal validateFields/save path.
 */
import { Button, Form, Input, Space } from "antd";
import { useTranslation } from "react-i18next";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";

export interface SampleTaskItem {
  title: string;
  prompt: string;
}

export interface ShowcaseItem {
  title: string;
  desc: string;
  tags?: string[];
}

export function SampleTasksEditor({ name = "sample_tasks" }: { name?: string }) {
  const { t } = useTranslation();
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {fields.map((field) => (
            <Space key={field.key} align="baseline" style={{ display: "flex" }}>
              <Form.Item
                name={[field.name, "title"]}
                rules={[{ required: true, message: "模板标题必填" }]}
                style={{ marginBottom: 0, width: 200 }}
              >
                <Input placeholder="模板标题（如：规划公众号菜单）" />
              </Form.Item>
              <Form.Item
                name={[field.name, "prompt"]}
                rules={[{ required: true, message: "提示词必填" }]}
                style={{ marginBottom: 0, flex: 1 }}
              >
                <Input.TextArea
                  rows={1}
                  placeholder="点击模板时发送的完整任务提示词"
                  autoSize={{ minRows: 1, maxRows: 3 }}
                />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => remove(field.name)}
                aria-label="删除模板"
              />
            </Space>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ title: "", prompt: "" })}
            icon={<PlusOutlined />}
            style={{ width: 220 }}
          >
            {t("admin.ops.addTask", "添加任务模板")}
          </Button>
        </div>
      )}
    </Form.List>
  );
}

export function ShowcaseEditor({ name = "showcase" }: { name?: string }) {
  const { t } = useTranslation();
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {fields.map((field) => (
            <Space key={field.key} align="baseline" style={{ display: "flex" }}>
              <Form.Item
                name={[field.name, "title"]}
                rules={[{ required: true, message: "案例标题必填" }]}
                style={{ marginBottom: 0, width: 200 }}
              >
                <Input placeholder="案例标题" />
              </Form.Item>
              <Form.Item
                name={[field.name, "desc"]}
                rules={[{ required: true, message: "案例摘要必填" }]}
                style={{ marginBottom: 0, flex: 1 }}
              >
                <Input.TextArea
                  rows={1}
                  placeholder="案例摘要（做了什么、结果如何）"
                  autoSize={{ minRows: 1, maxRows: 3 }}
                />
              </Form.Item>
              <Form.Item
                name={[field.name, "tags"]}
                style={{ marginBottom: 0, width: 180 }}
              >
                <Input placeholder="标签，逗号分隔" />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => remove(field.name)}
                aria-label="删除案例"
              />
            </Space>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ title: "", desc: "", tags: "" })}
            icon={<PlusOutlined />}
            style={{ width: 220 }}
          >
            {t("admin.ops.addCase", "添加使用案例")}
          </Button>
        </div>
      )}
    </Form.List>
  );
}

/** Form value tags (string) → wire tags (string[]) for showcase items. */
export function normalizeShowcase(
  items: Array<ShowcaseItem & { tags?: string | string[] }> | undefined,
): ShowcaseItem[] {
  return (items ?? []).map((item) => ({
    title: item.title ?? "",
    desc: item.desc ?? "",
    tags:
      typeof item.tags === "string"
        ? item.tags
            .split(/[,，]/)
            .map((s) => s.trim())
            .filter(Boolean)
        : (item.tags ?? []),
  }));
}
