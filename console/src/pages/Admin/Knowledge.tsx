/**
 * Admin/Knowledge — knowledge base fleet management (M5, wraps M4-5/M4-6).
 *
 * Covers every scope (personal/team/enterprise) plus explicit grants,
 * document ingestion, and document removal.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  adminKbApi,
  adminTeamsApi,
  adminUsersApi,
} from "../../api/modules/admin";
import type {
  KbDocumentView,
  KnowledgeBase,
  TeamRecord,
  AdminUserView,
} from "../../api/modules/admin";
import styles from "./admin.module.less";

const SCOPE_COLORS: Record<string, string> = {
  personal: "green",
  team: "orange",
  enterprise: "geekblue",
};

function KnowledgePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [docsKb, setDocsKb] = useState<KnowledgeBase | null>(null);
  const [docs, setDocs] = useState<KbDocumentView[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [ingestOpen, setIngestOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [ingestForm] = Form.useForm();
  const scopeValue = Form.useWatch("scope", createForm) ?? "personal";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setKbs(await adminKbApi.list());
    } catch (err) {
      console.error("Failed to load knowledge bases:", err);
      message.error(t("admin.kb.loadFailed", "Failed to load knowledge bases"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
    adminUsersApi.list().then(setUsers).catch(() => setUsers([]));
    adminTeamsApi.list().then(setTeams).catch(() => setTeams([]));
  }, [load]);

  const loadDocs = useCallback(
    async (kb: KnowledgeBase) => {
      setDocsLoading(true);
      try {
        setDocs(await adminKbApi.listDocuments(kb.id));
      } catch (err) {
        message.error(String(err));
      } finally {
        setDocsLoading(false);
      }
    },
    [message],
  );

  const openDocs = (kb: KnowledgeBase) => {
    setDocsKb(kb);
    loadDocs(kb);
  };

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    try {
      await adminKbApi.create(values);
      message.success(t("admin.kb.created", "Knowledge base created"));
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDeleteKb = async (kb: KnowledgeBase) => {
    try {
      await adminKbApi.remove(kb.id);
      message.success(t("admin.kb.deleted", "Knowledge base deleted"));
      if (docsKb?.id === kb.id) setDocsKb(null);
      load();
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleIngest = async () => {
    const values = await ingestForm.validateFields();
    if (!docsKb) return;
    try {
      const result = await adminKbApi.ingest(docsKb.id, values);
      message.success(
        t("admin.kb.ingested", "Ingested {count} chunk(s)").replace(
          "{count}",
          String(result.chunk_count),
        ),
      );
      setIngestOpen(false);
      ingestForm.resetFields();
      loadDocs(docsKb);
    } catch (err) {
      message.error(String(err));
    }
  };

  const handleDeleteDoc = async (doc: KbDocumentView) => {
    if (!docsKb) return;
    try {
      await adminKbApi.removeDocument(docsKb.id, doc.doc_id);
      loadDocs(docsKb);
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.admin", "Administration")}
        current={t("nav.adminKnowledge", "Knowledge Bases")}
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            {t("admin.kb.create", "New knowledge base")}
          </Button>
        }
      />
      <Table<KnowledgeBase>
        rowKey="id"
        loading={loading}
        dataSource={kbs}
        pagination={false}
        columns={[
          { title: t("admin.kb.name", "Name"), dataIndex: "name" },
          {
            title: t("admin.kb.scope", "Scope"),
            dataIndex: "scope",
            width: 120,
            render: (scope: string) => (
              <Tag color={SCOPE_COLORS[scope] ?? "default"}>{scope}</Tag>
            ),
          },
          {
            title: t("admin.kb.owner", "Owner / Team"),
            key: "owner",
            render: (_, kb) => kb.owner_id || kb.team_id || "—",
          },
          {
            title: t("admin.kb.grants", "Grants"),
            key: "grants",
            render: (_, kb) => (
              <>
                {kb.grants_roles.map((role) => (
                  <Tag key={`r-${role}`} color="geekblue">
                    role:{role}
                  </Tag>
                ))}
                {kb.grants_users.map((user) => (
                  <Tag key={`u-${user}`} color="green">
                    user:{user}
                  </Tag>
                ))}
                {kb.grants_teams.map((team) => (
                  <Tag key={`t-${team}`} color="orange">
                    team:{team}
                  </Tag>
                ))}
              </>
            ),
          },
          {
            title: t("admin.kb.createdAt", "Created"),
            dataIndex: "created_at",
            width: 150,
            render: (v: string) => (v ? dayjs(v).format("YYYY-MM-DD") : "—"),
          },
          {
            title: t("admin.kb.actions", "Actions"),
            key: "actions",
            width: 220,
            render: (_, kb) => (
              <>
                <Button size="small" onClick={() => openDocs(kb)}>
                  {t("admin.kb.documents", "Documents")}
                </Button>
                <Popconfirm
                  title={t(
                    "admin.kb.deleteConfirm",
                    "Delete this knowledge base and all its chunks?",
                  )}
                  onConfirm={() => handleDeleteKb(kb)}
                >
                  <Button size="small" danger style={{ marginLeft: 8 }}>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              </>
            ),
          },
        ]}
      />

      <Modal
        title={t("admin.kb.create", "New knowledge base")}
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        destroyOnHidden
      >
        <Form
          form={createForm}
          layout="vertical"
          preserve={false}
          initialValues={{ scope: "personal" }}
        >
          <Form.Item
            name="name"
            label={t("admin.kb.name", "Name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="scope"
            label={t("admin.kb.scope", "Scope")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "personal", label: "personal" },
                { value: "team", label: "team" },
                { value: "enterprise", label: "enterprise" },
              ]}
            />
          </Form.Item>
          {scopeValue === "personal" ? (
            <Form.Item
              name="owner_id"
              label={t("admin.kb.ownerUser", "Owner (user)")}
              rules={[{ required: true }]}
            >
              <Select
                showSearch
                options={users.map((user) => ({
                  value: user.username,
                  label: user.username,
                }))}
              />
            </Form.Item>
          ) : null}
          {scopeValue === "team" ? (
            <Form.Item
              name="team_id"
              label={t("admin.kb.ownerTeam", "Team")}
              rules={[{ required: true }]}
            >
              <Select
                showSearch
                options={teams.map((team) => ({
                  value: team.name,
                  label: team.name,
                }))}
              />
            </Form.Item>
          ) : null}
          <Form.Item
            name="description"
            label={t("admin.kb.description", "Description")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={docsKb?.name ?? ""}
        open={docsKb !== null}
        onClose={() => setDocsKb(null)}
        width={640}
        extra={
          <Button type="primary" onClick={() => setIngestOpen(true)}>
            {t("admin.kb.ingest", "Ingest text")}
          </Button>
        }
      >
        <Table<KbDocumentView>
          rowKey="doc_id"
          loading={docsLoading}
          dataSource={docs}
          pagination={false}
          columns={[
            {
              title: t("admin.kb.docTitle", "Title"),
              dataIndex: "title",
              render: (v: string) => v || "—",
            },
            {
              title: t("admin.kb.docChunks", "Chunks"),
              dataIndex: "chunk_count",
              width: 90,
            },
            {
              title: t("admin.kb.createdAt", "Created"),
              dataIndex: "created_at",
              width: 110,
              render: (v: string) => (v ? dayjs(v).format("YYYY-MM-DD") : "—"),
            },
            {
              title: "",
              key: "actions",
              width: 90,
              render: (_, doc) => (
                <Popconfirm
                  title={t("admin.kb.deleteDocConfirm", "Remove this document?")}
                  onConfirm={() => handleDeleteDoc(doc)}
                >
                  <Button size="small" danger>
                    {t("common.delete", "Delete")}
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Drawer>

      <Modal
        title={t("admin.kb.ingest", "Ingest text")}
        open={ingestOpen}
        onOk={handleIngest}
        onCancel={() => setIngestOpen(false)}
        destroyOnHidden
      >
        <Form form={ingestForm} layout="vertical" preserve={false}>
          <Form.Item name="title" label={t("admin.kb.docTitle", "Title")}>
            <Input />
          </Form.Item>
          <Form.Item name="source" label={t("admin.kb.docSource", "Source")}>
            <Input placeholder="runbook / wiki / ..." />
          </Form.Item>
          <Form.Item
            name="text"
            label={t("admin.kb.docText", "Text")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={8} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default KnowledgePage;
