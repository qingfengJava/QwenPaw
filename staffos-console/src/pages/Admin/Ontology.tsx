/**
 * Admin/Ontology — 业务本体对象/关系/关联管理（ontology runtime T4，前端 T7）。
 *
 * Structure: stat row + type filter（联动清空搜索，规范 §2.8）+ keyword
 * search → objects table（类型/状态/别名列居中）→ per-object Drawer
 * （relations 双向列表 + kb_object_links 关联编辑）。
 *
 * 枚举展示走后端 /ontology/types 与对象自带 status（不前端硬编码）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/staffdeck";
import { useAppMessage } from "../../hooks/useAppMessage";
import { adminOntologyApi } from "../../api/modules/admin";
import type {
  KbObjectLinkView,
  OntologyObjectView,
  OntologyRelationView,
  OntologyRelationsPairView,
  OntologyTypeView,
} from "../../api/modules/admin";
import { kbRequestError } from "./kbErrors";
import styles from "./admin.module.less";

const OBJECT_STATUS_TONE: Record<string, string> = {
  active: styles.toneGreen,
  retired: styles.toneGray,
};

interface RelationTarget {
  id: string;
  name: string;
}

/** 合并双向关系后的行（_direction 标记出/入向，供表格展示）。 */
type RelationRow = OntologyRelationView & {
  _direction: "outbound" | "inbound";
};

/** 后端返回 {outbound, inbound} 双向列表 → 合并为单表行（带方向标记）。 */
function mergeRelationRows(pair: OntologyRelationsPairView): RelationRow[] {
  return [
    ...pair.outbound.map((r) => ({ ...r, _direction: "outbound" as const })),
    ...pair.inbound.map((r) => ({ ...r, _direction: "inbound" as const })),
  ];
}

/** 关系类型选项（默认 relation 词表 + 自由输入，允许业务自定义）。 */
const RELATION_TYPE_OPTIONS = [
  "belongs_to",
  "owned_by",
  "manages",
  "reports_to",
  "part_of",
  "related_to",
  "precedes",
];

function OntologyPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [types, setTypes] = useState<OntologyTypeView[]>([]);
  const [objects, setObjects] = useState<OntologyObjectView[] | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [keyword, setKeyword] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<OntologyObjectView | null>(null);
  const [relationsFor, setRelationsFor] = useState<OntologyObjectView | null>(
    null,
  );
  const [relations, setRelations] = useState<RelationRow[] | null>(null);
  const [links, setLinks] = useState<KbObjectLinkView[] | null>(null);
  const [saving, setSaving] = useState(false);

  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [relationForm] = Form.useForm();
  const [linkForm] = Form.useForm();

  const typeName = useCallback(
    (typeId: string) => {
      const found = types.find((x) => x.id === typeId);
      return found ? `${found.name} (${typeId})` : typeId;
    },
    [types],
  );

  const loadTypes = useCallback(async () => {
    try {
      setTypes(await adminOntologyApi.listTypes());
    } catch (err) {
      // 503 = 本体平面不可用（enterprise pg 门控）：类型为空但页面可用
      setTypes([]);
      console.error("Failed to load ontology types:", err);
    }
  }, []);

  const loadObjects = useCallback(async () => {
    setObjects(null);
    try {
      setObjects(
        await adminOntologyApi.listObjects({
          q: keyword.trim() || undefined,
          type_id: typeFilter || undefined,
        }),
      );
    } catch (err) {
      setObjects([]);
      message.error(kbRequestError(err, t));
    }
  }, [keyword, message, t, typeFilter]);

  useEffect(() => {
    loadTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadObjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter]);

  // 类型筛选变化 → 联动清空关键词（规范 §2.8 上级变化清空下级）
  const handleTypeChange = (value: string) => {
    setTypeFilter(value);
    setKeyword("");
  };

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    setSaving(true);
    try {
      await adminOntologyApi.createObject({
        type_id: values.type_id,
        name: values.name,
        aliases: values.aliases ?? [],
        description: values.description ?? "",
      });
      message.success(t("ontology.createObjectSuccess", "对象已创建"));
      setCreateOpen(false);
      createForm.resetFields();
      loadObjects();
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (obj: OntologyObjectView) => {
    setEditing(obj);
    editForm.setFieldsValue({
      name: obj.name,
      aliases: obj.aliases,
      description: obj.description,
    });
  };

  const handleEdit = async () => {
    if (!editing) return;
    const values = await editForm.validateFields();
    setSaving(true);
    try {
      await adminOntologyApi.updateObject(editing.id, {
        name: values.name,
        aliases: values.aliases ?? [],
        description: values.description ?? "",
      });
      message.success(t("ontology.updateObjectSuccess", "对象已更新"));
      setEditing(null);
      loadObjects();
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveObject = async (obj: OntologyObjectView) => {
    try {
      await adminOntologyApi.removeObject(obj.id);
      message.success(t("ontology.removeObjectSuccess", "对象已删除"));
      loadObjects();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const openRelations = async (obj: OntologyObjectView) => {
    setRelationsFor(obj);
    setRelations(null);
    setLinks(null);
    relationForm.resetFields();
    linkForm.resetFields();
    try {
      const pair = await adminOntologyApi.listObjectRelations(obj.id);
      setRelations(mergeRelationRows(pair));
      setLinks(await adminOntologyApi.listLinks(obj.id));
    } catch (err) {
      setRelations([]);
      setLinks([]);
      message.error(kbRequestError(err, t));
    }
  };

  const handleCreateRelation = async () => {
    if (!relationsFor) return;
    const values = await relationForm.validateFields();
    // 后端 OntologyRelation 必填 from_type/to_type：终点类型从当前对象列表取
    const toType =
      (objects ?? []).find((o) => o.id === values.to_id)?.type_id ?? "";
    try {
      await adminOntologyApi.createRelation({
        from_type: relationsFor.type_id,
        from_id: relationsFor.id,
        to_type: toType,
        to_id: values.to_id,
        type: values.type,
      });
      message.success(t("ontology.createRelationSuccess", "关系已创建"));
      relationForm.resetFields();
      const pair = await adminOntologyApi.listObjectRelations(
        relationsFor.id,
      );
      setRelations(mergeRelationRows(pair));
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const handleRemoveRelation = async (relationId: string) => {
    if (!relationsFor) return;
    try {
      await adminOntologyApi.removeRelation(relationId);
      const pair = await adminOntologyApi.listObjectRelations(
        relationsFor.id,
      );
      setRelations(mergeRelationRows(pair));
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const handleCreateLink = async () => {
    if (!relationsFor) return;
    const values = await linkForm.validateFields();
    try {
      // 字段对齐后端 KbObjectLink：kb_space_id/kb_document_id/object_type
      await adminOntologyApi.createLink(relationsFor.id, {
        kb_space_id: values.kb_space_id,
        kb_document_id: values.kb_document_id,
        object_type: relationsFor.type_id,
        relation: values.relation || "knowledge_mentions",
      });
      message.success(t("ontology.createLinkSuccess", "关联已创建"));
      linkForm.resetFields();
      setLinks(await adminOntologyApi.listLinks(relationsFor.id));
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const handleRemoveLink = async (linkId: string) => {
    if (!relationsFor) return;
    try {
      await adminOntologyApi.removeLink(linkId);
      setLinks(await adminOntologyApi.listLinks(relationsFor.id));
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const targetOptions = useMemo<RelationTarget[]>(
    () =>
      (objects ?? [])
        .filter((obj) => obj.id !== relationsFor?.id)
        .map((obj) => ({ id: obj.id, name: obj.name })),
    [objects, relationsFor],
  );

  const l1Types = useMemo(
    () => types.filter((x) => x.layer !== "l0"),
    [types],
  );

  return (
    <div className={styles.page}>
      <PageHeader
        current={t("nav.adminOntology", "Ontology")}
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            {t("ontology.createObject", "新建对象")}
          </Button>
        }
      />

      <div className={styles.kbStatsRow}>
        <StatCard
          value={objects?.length ?? 0}
          label={t("ontology.statObjects", "业务对象")}
        />
        <div className={styles.kbFilterCard}>
          <Select
            allowClear
            value={typeFilter || undefined}
            onChange={(v) => handleTypeChange((v as string) ?? "")}
            placeholder={t("ontology.typeFilterPlaceholder", "按类型筛选")}
            style={{ width: 220 }}
            options={l1Types.map((x) => ({
              value: x.id,
              label: `${x.name} (${x.id})`,
            }))}
          />
          <Input.Search
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={loadObjects}
            placeholder={t("ontology.searchPlaceholder", "搜索对象名称")}
            style={{ width: 220 }}
          />
        </div>
      </div>

      <div className={styles.panel}>
        <Table<OntologyObjectView>
          rowKey="id"
          size="small"
          loading={objects === null}
          dataSource={objects ?? []}
          pagination={{ pageSize: 12, showSizeChanger: false }}
          locale={{
            emptyText: t("ontology.objectsEmpty", "暂无业务对象"),
          }}
          columns={[
            {
              title: t("ontology.objectName", "名称"),
              dataIndex: "name",
              align: "center" as const,
              ellipsis: true,
            },
            {
              title: t("ontology.objectType", "类型"),
              dataIndex: "type_id",
              width: 200,
              align: "center" as const,
              ellipsis: true,
              render: (v: string) => typeName(v),
            },
            {
              title: t("ontology.objectStatus", "状态"),
              dataIndex: "status",
              width: 96,
              align: "center" as const,
              render: (v: string) => (
                <span
                  className={`${styles.toneTag} ${
                    OBJECT_STATUS_TONE[v] ?? styles.toneGray
                  }`}
                >
                  {v}
                </span>
              ),
            },
            {
              title: t("ontology.objectAliases", "别名"),
              dataIndex: "aliases",
              align: "center" as const,
              ellipsis: true,
              render: (v: string[]) => (v.length ? v.join("、") : "—"),
            },
            {
              title: t("ontology.objectActions", "操作"),
              key: "actions",
              width: 240,
              align: "center" as const,
              render: (_: unknown, obj: OntologyObjectView) => (
                <>
                  <Button
                    size="small"
                    onClick={() => openRelations(obj)}
                    style={{ marginRight: 4 }}
                  >
                    {t("ontology.relationsAndLinks", "关系/关联")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => openEdit(obj)}
                    style={{ marginRight: 4 }}
                  >
                    {t("ontology.edit", "编辑")}
                  </Button>
                  <Popconfirm
                    title={t(
                      "ontology.removeConfirm",
                      "删除该对象（逻辑删除，可恢复）？",
                    )}
                    onConfirm={() => handleRemoveObject(obj)}
                  >
                    <Button size="small" danger>
                      {t("ontology.remove", "删除")}
                    </Button>
                  </Popconfirm>
                </>
              ),
            },
          ]}
        />
      </div>

      {/* 新建对象 */}
      <Modal
        title={t("ontology.createObject", "新建对象")}
        open={createOpen}
        onOk={handleCreate}
        confirmLoading={saving}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="type_id"
            label={t("ontology.objectType", "类型")}
            rules={[{ required: true }]}
          >
            <Select
              showSearch
              options={l1Types.map((x) => ({
                value: x.id,
                label: `${x.name} (${x.id})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("ontology.objectName", "名称")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="aliases" label={t("ontology.objectAliases", "别名")}>
            <Select mode="tags" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="description" label={t("knowledge.description", "描述")}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑对象 */}
      <Modal
        title={t("ontology.editObject", "编辑对象")}
        open={editing !== null}
        onOk={handleEdit}
        confirmLoading={saving}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("ontology.objectName", "名称")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="aliases" label={t("ontology.objectAliases", "别名")}>
            <Select mode="tags" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="description" label={t("knowledge.description", "描述")}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关系 / 关联抽屉 */}
      <Drawer
        title={
          relationsFor
            ? `${relationsFor.name} — ${t(
                "ontology.relationsAndLinks",
                "关系/关联",
              )}`
            : ""
        }
        open={relationsFor !== null}
        onClose={() => setRelationsFor(null)}
        width={720}
      >
        <div className={styles.kbPanelTitle}>
          {t("ontology.relations", "关系")}
        </div>
        <Table<RelationRow>
          rowKey="id"
          size="small"
          loading={relations === null}
          dataSource={relations ?? []}
          pagination={false}
          locale={{ emptyText: t("ontology.relationsEmpty", "暂无关系") }}
          columns={[
            {
              title: t("ontology.relationDirection", "方向"),
              dataIndex: "_direction",
              width: 72,
              align: "center" as const,
              render: (v: string) =>
                v === "outbound"
                  ? t("ontology.directionOutbound", "出向")
                  : t("ontology.directionInbound", "入向"),
            },
            {
              title: t("ontology.relationFrom", "起点"),
              dataIndex: "from_id",
              align: "center" as const,
              ellipsis: true,
            },
            {
              title: t("ontology.relationType", "关系类型"),
              dataIndex: "type",
              width: 120,
              align: "center" as const,
            },
            {
              title: t("ontology.relationTo", "终点"),
              dataIndex: "to_id",
              align: "center" as const,
              ellipsis: true,
            },
            {
              title: t("ontology.objectActions", "操作"),
              key: "del",
              width: 80,
              align: "center" as const,
              render: (_: unknown, row: RelationRow) => (
                <Popconfirm
                  title={t("ontology.removeRelationConfirm", "删除该关系？")}
                  onConfirm={() => handleRemoveRelation(row.id)}
                >
                  <Button size="small" danger>
                    {t("ontology.remove", "删除")}
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
        <Form
          form={relationForm}
          layout="inline"
          style={{ marginTop: 12, rowGap: 8 }}
          onFinish={handleCreateRelation}
        >
          <Form.Item name="type" rules={[{ required: true }]}>
            <Select
              showSearch
              placeholder={t("ontology.relationType", "关系类型")}
              style={{ width: 150 }}
              options={RELATION_TYPE_OPTIONS.map((x) => ({ value: x, label: x }))}
            />
          </Form.Item>
          <Form.Item name="to_id" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t("ontology.relationTo", "终点对象")}
              style={{ width: 220 }}
              options={targetOptions.map((x) => ({
                value: x.id,
                label: `${x.name} (${x.id})`,
              }))}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" size="small">
              {t("ontology.addRelation", "添加关系")}
            </Button>
          </Form.Item>
        </Form>

        <div className={styles.kbPanelTitle} style={{ marginTop: 24 }}>
          {t("ontology.links", "关联文档（kb_object_links）")}
        </div>
        <Table<KbObjectLinkView>
          rowKey="id"
          size="small"
          loading={links === null}
          dataSource={links ?? []}
          pagination={false}
          locale={{ emptyText: t("ontology.linksEmpty", "暂无关联") }}
          columns={[
            {
              title: t("ontology.linkKb", "知识库"),
              dataIndex: "kb_space_id",
              align: "center" as const,
              ellipsis: true,
            },
            {
              title: t("ontology.linkDoc", "文档"),
              dataIndex: "kb_document_id",
              align: "center" as const,
              ellipsis: true,
            },
            {
              title: t("ontology.linkRelation", "关系"),
              dataIndex: "relation",
              width: 160,
              align: "center" as const,
            },
            {
              title: t("ontology.objectActions", "操作"),
              key: "del",
              width: 80,
              align: "center" as const,
              render: (_: unknown, row: KbObjectLinkView) => (
                <Popconfirm
                  title={t("ontology.removeLinkConfirm", "删除该关联？")}
                  onConfirm={() => handleRemoveLink(row.id)}
                >
                  <Button size="small" danger>
                    {t("ontology.remove", "删除")}
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
        <Form
          form={linkForm}
          layout="inline"
          style={{ marginTop: 12, rowGap: 8 }}
          onFinish={handleCreateLink}
        >
          <Form.Item name="kb_space_id" rules={[{ required: true }]}>
            <Input placeholder={t("ontology.linkKb", "知识库 ID")} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="kb_document_id" rules={[{ required: true }]}>
            <Input placeholder={t("ontology.linkDoc", "文档 ID")} style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="relation" initialValue="knowledge_mentions">
            <Input placeholder={t("ontology.linkRelation", "关系")} style={{ width: 170 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" size="small">
              {t("ontology.addLink", "添加关联")}
            </Button>
          </Form.Item>
        </Form>
        {relationsFor === null && objects === null ? (
          <Empty description={null} />
        ) : null}
      </Drawer>
    </div>
  );
}

export default OntologyPage;
