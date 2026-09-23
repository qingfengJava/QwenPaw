/**
 * Admin/Knowledge — knowledge base fleet management (KB phase 1, T12 rebuild).
 *
 * Structure: stat row + scope UnderlineTabs (联动清空 search on switch) +
 * keyword search → KB card grid (「画布+面」surface tiles: scope label via
 * enum description text, grants tags, owner/team meta) → per-space
 * management Drawer (KnowledgeDrawer: doc tree + MD editor + upload +
 * chunk preview + search-test bench).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
} from "antd";
import {
  DeleteOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import dayjs from "dayjs";
import { PageHeader } from "@/components/PageHeader";
import { StatCard, UnderlineTabs } from "@/components/staffdeck";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  adminKbApi,
  adminTeamsApi,
  adminUsersApi,
} from "../../api/modules/admin";
import type {
  AdminUserView,
  KnowledgeBase,
  TeamRecord,
} from "../../api/modules/admin";
import KnowledgeDrawer from "./KnowledgeDrawer";
import { kbRequestError } from "./kbErrors";
import styles from "./admin.module.less";

type ScopeFilter = "all" | "personal" | "team" | "enterprise";

const SCOPE_TONE_CLASS: Record<string, string> = {
  personal: styles.toneGreen,
  team: styles.toneAmber,
  enterprise: styles.toneBlue,
};

const SCOPE_LABEL_KEY: Record<string, string> = {
  personal: "knowledge.scopePersonal",
  team: "knowledge.scopeTeam",
  enterprise: "knowledge.scopeEnterprise",
};

function scopeText(kb: KnowledgeBase, t: TFunction): string {
  return t(SCOPE_LABEL_KEY[kb.scope] ?? "", kb.scope);
}

function formatDate(value: string | undefined): string {
  return value ? dayjs(value).format("YYYY-MM-DD") : "—";
}

function KnowledgePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [users, setUsers] = useState<AdminUserView[]>([]);
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [drawerKb, setDrawerKb] = useState<KnowledgeBase | null>(null);
  const [createForm] = Form.useForm();
  const scopeValue = Form.useWatch("scope", createForm) ?? "personal";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setKbs(await adminKbApi.list());
    } catch (err) {
      console.error("Failed to load knowledge bases:", err);
      message.error(t("knowledge.loadFailed", "加载知识库失败"));
    } finally {
      setLoading(false);
    }
  }, [message, t]);

  useEffect(() => {
    load();
    adminUsersApi.list().then(setUsers).catch(() => setUsers([]));
    adminTeamsApi.list().then(setTeams).catch(() => setTeams([]));
  }, [load]);

  // scope 筛选 → 关键词联动清空（多级筛选联动清空规范）
  const handleScopeChange = (key: string) => {
    setScopeFilter(key as ScopeFilter);
    setKeyword("");
  };

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return kbs.filter((kb) => {
      if (scopeFilter !== "all" && kb.scope !== scopeFilter) return false;
      if (!kw) return true;
      return (
        kb.name.toLowerCase().includes(kw) ||
        kb.description.toLowerCase().includes(kw)
      );
    });
  }, [kbs, scopeFilter, keyword]);

  const counts = useMemo(
    () => ({
      all: kbs.length,
      personal: kbs.filter((k) => k.scope === "personal").length,
      team: kbs.filter((k) => k.scope === "team").length,
      enterprise: kbs.filter((k) => k.scope === "enterprise").length,
    }),
    [kbs],
  );

  const handleCreate = async () => {
    const values = await createForm.validateFields();
    try {
      await adminKbApi.create(values);
      message.success(t("knowledge.createKbSuccess", "知识库已创建"));
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const handleDeleteKb = async (kb: KnowledgeBase) => {
    try {
      await adminKbApi.remove(kb.id);
      message.success(t("knowledge.deleteKbSuccess", "知识库已删除"));
      if (drawerKb?.id === kb.id) setDrawerKb(null);
      load();
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const tabItems = [
    { key: "all", label: t("knowledge.filterAll", "全部"), count: counts.all },
    {
      key: "personal",
      label: t("knowledge.filterPersonal", "个人"),
      count: counts.personal,
    },
    { key: "team", label: t("knowledge.filterTeam", "团队"), count: counts.team },
    {
      key: "enterprise",
      label: t("knowledge.filterEnterprise", "企业"),
      count: counts.enterprise,
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        current={t("nav.adminKnowledge", "Knowledge Bases")}
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            {t("knowledge.createKb", "新建知识库")}
          </Button>
        }
      />

      <div className={styles.kbLayout}>
        {/* 统计 + 筛选 + 搜索行 */}
        <div className={styles.kbStatsRow}>
          <StatCard value={counts.all} label={t("knowledge.statTotal", "知识库")} />
          <div className={styles.kbFilterCard}>
            <UnderlineTabs
              items={tabItems}
              value={scopeFilter}
              onChange={handleScopeChange}
            />
            <Input
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder={t("knowledge.searchPlaceholder", "搜索名称 / 描述")}
              prefix={<FileTextOutlined style={{ color: "var(--pg-ink-3)" }} />}
              style={{ width: 220 }}
            />
          </div>
        </div>

        {/* 库卡片网格 */}
        {loading ? null : filtered.length === 0 ? (
          <div className={styles.panel}>
            <Empty
              description={
                kbs.length === 0
                  ? t("knowledge.emptyAll", "还没有知识库，点击右上角新建")
                  : t("knowledge.emptyFiltered", "当前筛选条件下暂无知识库")
              }
              style={{ padding: "40px 0" }}
            />
          </div>
        ) : (
          <div className={styles.kbGrid}>
            {filtered.map((kb) => (
              <article
                key={kb.id}
                className={styles.kbCard}
                onClick={() => setDrawerKb(kb)}
              >
                <div className={styles.kbCardHead}>
                  <FolderOpenOutlined className={styles.kbCardIcon} />
                  <span className={styles.kbCardName} title={kb.name}>
                    {kb.name}
                  </span>
                  <span
                    className={`${styles.toneTag} ${
                      SCOPE_TONE_CLASS[kb.scope] ?? styles.toneGray
                    }`}
                  >
                    {scopeText(kb, t)}
                  </span>
                </div>
                <p className={styles.kbCardDesc}>
                  {kb.description || t("knowledge.cardNoDesc", "暂无描述")}
                </p>
                <div className={styles.kbCardMeta}>
                  <span>
                    {kb.owner_id
                      ? `${t("knowledge.ownerUser", "归属用户")}：${kb.owner_id}`
                      : kb.team_id
                        ? `${t("knowledge.ownerTeam", "归属团队")}：${kb.team_id}`
                        : "—"}
                  </span>
                  <span>
                    {t("knowledge.createdAt", "创建于")} {formatDate(kb.created_at)}
                  </span>
                </div>
                <div className={styles.kbCardGrants}>
                  {kb.grants_roles.map((role) => (
                    <span key={`r-${role}`} className={styles.toneBlue}>
                      {t("knowledge.grantRole", "角色")}：{role}
                    </span>
                  ))}
                  {kb.grants_users.map((user) => (
                    <span key={`u-${user}`} className={styles.toneGreen}>
                      {t("knowledge.grantUser", "用户")}：{user}
                    </span>
                  ))}
                  {kb.grants_teams.map((team) => (
                    <span key={`t-${team}`} className={styles.toneAmber}>
                      {t("knowledge.grantTeam", "团队")}：{team}
                    </span>
                  ))}
                  {!kb.grants_roles.length &&
                  !kb.grants_users.length &&
                  !kb.grants_teams.length ? (
                    <span className={styles.kbCardNoGrants}>
                      {t("knowledge.grantsEmpty", "未配置授权")}
                    </span>
                  ) : null}
                </div>
                <div
                  className={styles.kbCardActions}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() => setDrawerKb(kb)}
                  >
                    {t("knowledge.manageDocs", "管理文档")}
                  </Button>
                  <Popconfirm
                    title={t(
                      "knowledge.deleteKbConfirm",
                      "删除该知识库及其全部文档与切片？",
                    )}
                    onConfirm={() => handleDeleteKb(kb)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* 新建弹窗 */}
      <Modal
        title={t("knowledge.createKb", "新建知识库")}
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
            label={t("knowledge.name", "名称")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="scope"
            label={t("knowledge.scopeLabel", "范围")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                {
                  value: "personal",
                  label: t("knowledge.scopePersonal", "个人库"),
                },
                { value: "team", label: t("knowledge.scopeTeam", "团队库") },
                {
                  value: "enterprise",
                  label: t("knowledge.scopeEnterprise", "企业库"),
                },
              ]}
            />
          </Form.Item>
          {scopeValue === "personal" ? (
            <Form.Item
              name="owner_id"
              label={t("knowledge.ownerUser", "归属用户")}
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
              label={t("knowledge.ownerTeam", "归属团队")}
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
            label={t("knowledge.description", "描述")}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 库详情抽屉：key 绑定库 id，切换库时整体重挂载实现联动清空 */}
      {drawerKb ? (
        <KnowledgeDrawer
          key={drawerKb.id}
          kb={drawerKb}
          onClose={() => setDrawerKb(null)}
        />
      ) : null}
    </div>
  );
}

export default KnowledgePage;
