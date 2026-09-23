/**
 * Xian/Knowledge — 员工知识工作区（T7）。
 *
 * 我的库卡片（/xian/knowledge/bases，owner==viewer）→ 点开管理抽屉：
 * 复用 Admin/KnowledgeDrawer（文档树/编辑/上传/检索测试/治理，员工面
 * /kb 人侧端点同构）+ 「绑定到我的数字员工」流程（T6 员工绑定 API）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Empty,
  Modal,
  Popconfirm,
  Select,
} from "antd";
import { DeleteOutlined, FolderOpenOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { employeeKnowledgeApi } from "../../../api/modules/employeeKb";
import type {
  ExpertBindingView,
  MyExpertView,
  MyKbView,
} from "../../../api/modules/employeeKb";
import KnowledgeDrawer from "../../Admin/KnowledgeDrawer";
import { kbRequestError } from "../../Admin/kbErrors";
import styles from "../../Admin/admin.module.less";
import type { KnowledgeBase } from "../../../api/modules/admin";

type KbLike = KnowledgeBase;

function toKbLike(base: MyKbView): KbLike {
  return {
    id: base.id,
    name: base.name,
    scope: "personal" as const,
    owner_id: "",
    team_id: "",
    description: base.description,
    grants_roles: [],
    grants_users: [],
    grants_teams: [],
    created_at: "",
  };
}

function KnowledgeWorkspace() {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  const [bases, setBases] = useState<MyKbView[] | null>(null);
  const [drawerKb, setDrawerKb] = useState<KbLike | null>(null);

  // 绑定弹窗状态
  const [bindFor, setBindFor] = useState<MyKbView | null>(null);
  const [experts, setExperts] = useState<MyExpertView[]>([]);
  const [bindings, setBindings] = useState<ExpertBindingView[]>([]);
  const [selectedExpert, setSelectedExpert] = useState<string>("");
  const [bindingBusy, setBindingBusy] = useState(false);

  const loadBases = useCallback(async () => {
    setBases(null);
    try {
      setBases(await employeeKnowledgeApi.listMyBases());
    } catch (err) {
      setBases([]);
      message.error(kbRequestError(err, t));
    }
  }, [message, t]);

  useEffect(() => {
    loadBases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openBindings = async (base: MyKbView) => {
    setBindFor(base);
    setBindings([]);
    setSelectedExpert("");
    try {
      const [myExperts, rows] = await Promise.all([
        employeeKnowledgeApi.listMyExperts(),
        employeeKnowledgeApi.listExpertBindings(base.id),
      ]);
      setExperts(myExperts);
      setBindings(rows);
    } catch (err) {
      setExperts([]);
      message.error(kbRequestError(err, t));
    }
  };

  const handleBind = async () => {
    if (!bindFor || !selectedExpert) return;
    setBindingBusy(true);
    try {
      await employeeKnowledgeApi.bindExpert(bindFor.id, selectedExpert);
      message.success(t("knowledge.bindExpertSuccess", "已绑定到我的专家"));
      setBindings(await employeeKnowledgeApi.listExpertBindings(bindFor.id));
      setSelectedExpert("");
    } catch (err) {
      message.error(kbRequestError(err, t));
    } finally {
      setBindingBusy(false);
    }
  };

  const handleUnbind = async (expertId: string) => {
    if (!bindFor) return;
    try {
      await employeeKnowledgeApi.unbindExpert(bindFor.id, expertId);
      setBindings(await employeeKnowledgeApi.listExpertBindings(bindFor.id));
    } catch (err) {
      message.error(kbRequestError(err, t));
    }
  };

  const boundIds = new Set(bindings.map((b) => b.expert_id));

  return (
    <div className={styles.page}>
      <PageHeader
        current={t("nav.myKnowledge", "My Knowledge")}
        extra={
          <Button onClick={loadBases}>
            {t("knowledge.refresh", "刷新")}
          </Button>
        }
      />

      {bases === null ? null : bases.length === 0 ? (
        <div className={styles.panel}>
          <Empty
            description={t(
              "knowledge.myKbEmpty",
              "你还没有个人知识库，可在检索/工作流中创建",
            )}
            style={{ padding: "40px 0" }}
          />
        </div>
      ) : (
        <div className={styles.kbGrid}>
          {bases.map((base) => (
            <article
              key={base.id}
              className={styles.kbCard}
              onClick={() => setDrawerKb(toKbLike(base))}
            >
              <div className={styles.kbCardHead}>
                <FolderOpenOutlined className={styles.kbCardIcon} />
                <span className={styles.kbCardName} title={base.name}>
                  {base.name}
                </span>
                <span className={`${styles.toneTag} ${styles.toneGreen}`}>
                  {t("knowledge.scopePersonal", "个人")}
                </span>
              </div>
              <p className={styles.kbCardDesc}>
                {base.description || t("knowledge.cardNoDesc", "暂无描述")}
              </p>
              <div
                className={styles.kbCardActions}
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  size="small"
                  type="primary"
                  ghost
                  onClick={() => setDrawerKb(toKbLike(base))}
                >
                  {t("knowledge.manageDocs", "管理文档")}
                </Button>
                <Button size="small" onClick={() => openBindings(base)}>
                  {t("knowledge.bindExpert", "绑定到我的专家")}
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* 文档管理抽屉（复用管理端组件，员工面 /kb 人侧端点） */}
      {drawerKb ? (
        <KnowledgeDrawer
          key={drawerKb.id}
          kb={drawerKb}
          onClose={() => setDrawerKb(null)}
        />
      ) : null}

      {/* 绑定我的专家弹窗 */}
      <Modal
        title={
          bindFor
            ? `${bindFor.name} — ${t("knowledge.bindExpert", "绑定到我的专家")}`
            : ""
        }
        open={bindFor !== null}
        onCancel={() => setBindFor(null)}
        footer={null}
        destroyOnHidden
      >
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <Select
            showSearch
            optionFilterProp="label"
            value={selectedExpert || undefined}
            onChange={(v) => setSelectedExpert((v as string) ?? "")}
            placeholder={t(
              "knowledge.bindExpertPlaceholder",
              "选择我的专家（数字员工）",
            )}
            style={{ flex: 1 }}
            options={experts
              .filter((x) => !boundIds.has(x.id))
              .map((x) => ({ value: x.id, label: x.name }))}
          />
          <Button
            type="primary"
            disabled={!selectedExpert}
            loading={bindingBusy}
            onClick={handleBind}
          >
            {t("knowledge.bind", "绑定")}
          </Button>
        </div>
        {bindings.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("knowledge.bindingsEmpty", "尚未绑定任何专家")}
          />
        ) : (
          bindings.map((row) => (
            <div
              key={row.expert_id}
              className={styles.kbCardMeta}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span style={{ flex: 1 }}>
                {row.expert_name || row.expert_id}
              </span>
              <Popconfirm
                title={t("knowledge.unbindConfirm", "解除该绑定？")}
                onConfirm={() => handleUnbind(row.expert_id)}
              >
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </div>
          ))
        )}
      </Modal>
    </div>
  );
}

export default KnowledgeWorkspace;
