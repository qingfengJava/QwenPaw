/**
 * sop/ExpertSopPanel.tsx — 员工私有 SOP 能力面板（SOP 私有能力化，20260914）。
 *
 * SOP 重定位为数字员工 1:1 私有能力：面板内闭环——新建（草稿）→
 * 画布编辑 → 发布并生效（后端自动绑定本员工）→ 从其他员工复制副本 →
 * 版本历史/回滚 → 停用（解绑）/ 删除。绑定关系仍是
 * expert_resource_bindings 权威（运行时 D3 注入链路不变）。
 * 设计依据: docs/superpowers/specs/2026-09-14-sop-employee-owned-capability-design.md
 * @author qingfeng
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Table,
} from "antd";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import { SopFlowCanvas } from "./SopFlowCanvas";
import { SopFlowPreview, StatusPill } from "@/components/staffdeck";
import {
  expertCapabilityApi,
  sopApi,
  type ResourceType,
  type SopRecord,
  type SopVersion,
} from "@/api/modules/admin";

/**
 * 员工私有的 SOP 能力面板：列表卡片 + 全生命周期操作闭环。
 *
 * @param expertId 归属员工 id（SOP 以 owner_id 强归属本员工）
 * @param onChanged 资产/绑定变更后回调（父级刷新头部计数等）
 * @param onOpenCanvas 画布打开方式上抛（工作台传入：导航到 /studio/:aid/sop/:sopId
 *   下钻页）；不传时回落本地 Drawer（管理端 ExpertDetailPage）
 */
export function ExpertSopPanel({
  expertId,
  onChanged,
  onOpenCanvas,
}: {
  expertId: string;
  onChanged: () => Promise<void> | void;
  onOpenCanvas?: (sop: SopRecord) => void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  // 工作台宿主（传入 onOpenCanvas）：SOP 发布收敛到员工顶栏统一闸门，隐藏独立发布入口
  const workbench = Boolean(onOpenCanvas);

  // owner=本员工的全部 SOP（full 投影含节点，卡片可显示步骤/槽位数）
  const [sops, setSops] = useState<SopRecord[]>([]);
  // 已绑定（生效）的 sop id 集合
  const [boundIds, setBoundIds] = useState<Set<string>>(new Set());
  // 新建弹窗
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();
  // 复制弹窗（搜索全租户非本人 SOP）
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyKeyword, setCopyKeyword] = useState("");
  const [copyResults, setCopyResults] = useState<SopRecord[]>([]);
  const [copyLoading, setCopyLoading] = useState(false);
  // 画布编辑 / 只读预览 / 版本历史 抽屉（onOpenCanvas 模式下画布抽屉不启用）
  const [editingSop, setEditingSop] = useState<SopRecord | null>(null);
  const [previewSopId, setPreviewSopId] = useState("");
  const [historySop, setHistorySop] = useState<SopRecord | null>(null);
  const [versions, setVersions] = useState<SopVersion[]>([]);

  const load = useCallback(async () => {
    try {
      const [ownerSops, res] = await Promise.all([
        sopApi.list("", "", expertId, true),
        expertCapabilityApi.listResources(expertId),
      ]);
      setSops(ownerSops);
      setBoundIds(
        new Set((res.bindings?.sop ?? []).map((r) => r.resource_id)),
      );
    } catch (err) {
      message.error(String(err));
    }
  }, [expertId, message]);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = async () => {
    await load();
    await onChanged();
  };

  // ---- AI 实时联动：订阅员工级 SOP 活动流（画布跟随 + 列表同步） ----

  // 最新 refresh 经 ref 传递：onChanged 引用每次渲染都变，避免重订阅
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  // 列表刷新节流定时器（AI 逐步 update 密集事件，800ms trailing 合并）
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 面板级订阅：AI 新建 SOP 时前端尚不知 sop_id，经员工级轻量流感知
  // created 后自动打开画布（ensureDraft 拿草稿）；画布打开后的实时
  // 重绘由 SopFlowCanvas 内部的 sop 级订阅接管，面板只管列表与状态。
  // 工作台模式（onOpenCanvas 上抛）下自动下钻由外壳级订阅负责，
  // 面板只刷列表，避免双开/双 ensureDraft。
  // onOpenCanvas 经 ref 读取：调用方内联箭头函数引用每次渲染都变，
  // 避免订阅 effect 反复重连。
  const onOpenCanvasRef = useRef(onOpenCanvas);
  onOpenCanvasRef.current = onOpenCanvas;
  useEffect(() => {
    if (!expertId) {
      return;
    }
    const controller = new AbortController();
    void (async () => {
      try {
        await sopApi.streamExpertEvents(
          expertId,
          (event) => {
            if (event.action === "created") {
              // AI 刚新建草稿：刷新列表；画布打开见下方分支
              void refreshRef.current();
              if (onOpenCanvasRef.current) {
                return;
              }
              void (async () => {
                try {
                  const draft = await sopApi.ensureDraft(event.sop_id);
                  setEditingSop((current) =>
                    current?.id === draft.id ? current : draft,
                  );
                } catch {
                  // 拉草稿失败静默：列表里仍可手动打开
                }
              })();
              return;
            }
            // updated（草稿编辑）/published（升版本+绑定）只刷列表与
            // 状态；画布开着时实时重绘由画布内 sop 级订阅负责
            if (refreshTimer.current) {
              return;
            }
            refreshTimer.current = setTimeout(() => {
              refreshTimer.current = null;
              void refreshRef.current();
            }, 800);
          },
          controller.signal,
        );
      } catch {
        // 流中断（切页/网络抖动）静默——下次进入面板重新订阅
      }
    })();
    return () => {
      controller.abort();
      if (refreshTimer.current) {
        clearTimeout(refreshTimer.current);
        refreshTimer.current = null;
      }
    };
  }, [expertId]);

  /** 状态胶囊：区分草稿环境（未发布变更/纯草稿）与线上环境（生效/未生效）。 */
  const statusOf = (sop: SopRecord) => {
    // 合并列表优先返回草稿行：草稿行存在即代表有未发布编辑
    if (sop.environment === "draft") {
      if (boundIds.has(sop.id)) {
        return {
          tone: "amber" as const,
          label: t("staffdeck.sopPanel.hasUnpublished", "有未发布变更"),
        };
      }
      return {
        tone: "blue" as const,
        label: t("staffdeck.sopPanel.draft", "草稿"),
      };
    }
    if (sop.status === "published" && boundIds.has(sop.id)) {
      return {
        tone: "green" as const,
        label: t("staffdeck.sopPanel.active", "生效中"),
      };
    }
    if (sop.status === "draft") {
      return {
        tone: "blue" as const,
        label: t("staffdeck.sopPanel.draft", "草稿"),
      };
    }
    return {
      tone: "amber" as const,
      label: t("staffdeck.sopPanel.inactive", "未生效"),
    };
  };

  /** 打开画布统一入口：工作台模式上抛导航（下钻页），管理端回落本地 Drawer。 */
  const openCanvas = (sop: SopRecord) => {
    if (onOpenCanvas) {
      onOpenCanvas(sop);
      return;
    }
    setEditingSop(sop);
  };

  /** 打开画布编辑：存量线上 SOP 先 fork 出可编辑草稿行再进画布。 */
  const openEditor = async (sop: SopRecord) => {
    try {
      const draft = await sopApi.ensureDraft(sop.id);
      openCanvas(draft);
    } catch (err) {
      message.error(String(err));
    }
  };

  /** 让 AI 帮我画：预填引导指令到工作台聊天，由 AI 调 sop_* 工具生成。 */
  const askAiGenerate = () => {
    const goal = String(createForm.getFieldValue("goal") ?? "").trim();
    const name = String(createForm.getFieldValue("name") ?? "").trim();
    const hint = goal || name;
    const prompt = t(
      "staffdeck.sopPanel.aiGeneratePrompt",
      hint
        ? `请帮我设计一条 SOP 流程：{{hint}}。用 sop_create_draft 新建草稿、sop_update_draft 逐步补充节点/连线/槽位，右侧画布会实时跟随绘制。`
        : "请帮我设计一条 SOP 流程：先问我流程名称与总目标，再用 sop_create_draft / sop_update_draft 逐步补充节点、连线与槽位，右侧画布会实时跟随绘制。",
      { hint },
    );
    setCreating(false);
    // 工作台外壳监听本事件并切左侧聊天预填（跨借壳页解耦）
    window.dispatchEvent(
      new CustomEvent("qwenpaw:ai-tune-request", { detail: prompt }),
    );
  };

  const publish = async (sopId: string) => {
    try {
      await sopApi.publish(sopId, expertId);
      message.success(t("staffdeck.sopPanel.published", "已发布并生效"));
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  const unbind = async (sopId: string) => {
    try {
      const res = await expertCapabilityApi.listResources(expertId);
      const next = Object.entries(res.bindings ?? {}).flatMap(
        ([type, rows]) =>
          rows
            .filter((row) => !(type === "sop" && row.resource_id === sopId))
            .map((row) => ({ ...row, resource_type: type as ResourceType })),
      );
      await expertCapabilityApi.replaceResources(expertId, next);
      message.success(
        t("staffdeck.sopPanel.deactivated", "已停用（不再注入任务规划）"),
      );
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  const remove = async (sopId: string) => {
    try {
      await sopApi.remove(sopId);
      message.success(t("staffdeck.sopPanel.deleted", "已删除"));
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  const searchCopiable = async () => {
    setCopyLoading(true);
    try {
      const all = await sopApi.list("", copyKeyword.trim());
      setCopyResults(
        all.filter((s) => s.owner_id !== expertId && s.status !== "archived"),
      );
    } catch (err) {
      message.error(String(err));
    } finally {
      setCopyLoading(false);
    }
  };

  const duplicate = async (sop: SopRecord) => {
    try {
      await sopApi.duplicate(sop.id, expertId);
      message.success(
        t("staffdeck.sopPanel.copied", "已复制为本员工草稿，请检查后发布"),
      );
      setCopyOpen(false);
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  const openHistory = async (sop: SopRecord) => {
    setHistorySop(sop);
    try {
      setVersions((await sopApi.versions(sop.id)).versions ?? []);
    } catch (err) {
      message.error(String(err));
    }
  };

  const rollback = async (version: number) => {
    if (!historySop) {
      return;
    }
    try {
      await sopApi.rollback(historySop.id, version);
      message.success(
        t("staffdeck.sopPanel.rolledBack", "已恢复到草稿，点员工『发布』后生效"),
      );
      setVersions((await sopApi.versions(historySop.id)).versions ?? []);
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className="sd-card" style={{ padding: "20px 24px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.res.sop", "SOP 流程资产")}
        </span>
        <Space>
          <Button
            size="small"
            onClick={() => {
              // 表单干净由 Modal destroyOnHidden + Form preserve={false} 保证，
              // 不可在打开前调 resetFields（Form 尚未挂载会报 not connected 警告）
              setCreating(true);
            }}
          >
            {t("staffdeck.sopPanel.create", "+ 新建 SOP")}
          </Button>
          <Button
            size="small"
            onClick={() => {
              setCopyOpen(true);
              setCopyKeyword("");
              setCopyResults([]);
            }}
          >
            {t("staffdeck.sopPanel.copy", "从其他员工复制")}
          </Button>
        </Space>
      </div>

      {workbench && sops.length > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 10 }}
          message={t(
            "staffdeck.sopPanel.publishViaExpert",
            "流程修改后需点右上角『发布』对员工生效",
          )}
        />
      )}

      {sops.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--sd-text-3)" }}>
          {t(
            "staffdeck.sopPanel.empty",
            "尚无本员工的 SOP：新建流程沉淀经验，或从其他员工复制一份副本",
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {sops.map((sop) => {
            const status = statusOf(sop);
            const mounted = boundIds.has(sop.id);
            return (
              <div
                key={sop.id}
                style={{
                  padding: "10px 14px",
                  border: "0.5px solid var(--sd-line)",
                  borderRadius: "var(--sd-radius-lg)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <span
                    style={{
                      flex: 1,
                      fontSize: 13,
                      fontWeight: 600,
                      color: "var(--sd-ink)",
                    }}
                  >
                    {sop.name}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                    v{sop.version} · {(sop.nodes ?? []).length}{" "}
                    {t("staffdeck.sopPanel.steps", "步骤")} ·{" "}
                    {(sop.slots ?? []).length}{" "}
                    {t("staffdeck.sopPanel.slots", "槽位")}
                  </span>
                  <StatusPill tone={status.tone}>{status.label}</StatusPill>
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: "var(--sd-text-3)" }}>
                  {sop.goal || t("staffdeck.sopPanel.noGoal", "（未填总目标）")}
                </div>
                {sop.status === "draft" ? (
                  <div
                    style={{
                      marginTop: 2,
                      fontSize: 12,
                      color: "var(--sd-amber, #d97706)",
                    }}
                  >
                    {t(
                      "staffdeck.sopPanel.draftHint",
                      "草稿不生效，发布后注入任务规划",
                    )}
                  </div>
                ) : null}
                <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    onClick={() => void openEditor(sop)}
                  >
                    {t("staffdeck.sopPanel.canvasEdit", "画布编辑")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => setPreviewSopId(sop.id)}
                  >
                    {t("staffdeck.res.view", "预览")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => void openHistory(sop)}
                  >
                    {t("staffdeck.sopPanel.history", "版本历史")}
                  </Button>
                  {!workbench && (
                    <Button
                      size="small"
                      className="sd-btn-primary"
                      onClick={() => void publish(sop.id)}
                    >
                      {t("staffdeck.sopPanel.publish", "发布并生效")}
                    </Button>
                  )}
                  {mounted ? (
                    <Popconfirm
                      title={t(
                        "staffdeck.sopPanel.deactivateConfirm",
                        "停用后本员工不再注入该流程，确认？",
                      )}
                      onConfirm={() => void unbind(sop.id)}
                    >
                      <Button size="small">
                        {t("staffdeck.sopPanel.deactivate", "停用")}
                      </Button>
                    </Popconfirm>
                  ) : (
                    <Popconfirm
                      title={t(
                        "staffdeck.sopPanel.deleteConfirm",
                        "删除该 SOP（含版本历史）？",
                      )}
                      onConfirm={() => void remove(sop.id)}
                    >
                      <Button size="small" danger>
                        {t("staffdeck.sopPanel.delete", "删除")}
                      </Button>
                    </Popconfirm>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 新建：填基本信息后立即进入画布，或转交 AI 对话生成 */}
      <Modal
        title={t("staffdeck.sopPanel.createTitle", "新建 SOP")}
        open={creating}
        destroyOnHidden
        okText={t("staffdeck.sopPanel.createToCanvas", "创建并进入画布")}
        footer={(_, { OkBtn, CancelBtn }) => (
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 8,
              marginTop: 4,
            }}
          >
            <Button onClick={askAiGenerate}>
              {t("staffdeck.sopPanel.aiGenerate", "让 AI 帮我画")}
            </Button>
            <CancelBtn />
            <OkBtn />
          </div>
        )}
        onOk={async () => {
          const values = await createForm.validateFields();
          try {
            const created = await sopApi.create({
              name: values.name,
              goal: values.goal ?? "",
              business_domain: values.business_domain ?? "",
              owner_expert_id: expertId,
            });
            setCreating(false);
            await load();
            openCanvas(created);
          } catch (err) {
            message.error(String(err));
          }
        }}
        onCancel={() => setCreating(false)}
      >
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t("staffdeck.sopPanel.fieldName", "流程名称")}
            rules={[
              {
                required: true,
                message: t("staffdeck.sopPanel.nameRequired", "请填写流程名称"),
              },
            ]}
          >
            <Input
              placeholder={t(
                "staffdeck.sopPanel.namePlaceholder",
                "如：售后退款处理流程",
              )}
            />
          </Form.Item>
          <Form.Item
            name="goal"
            label={t("staffdeck.sopPanel.fieldGoal", "总目标（一句话）")}
          >
            <Input
              placeholder={t(
                "staffdeck.sopPanel.goalPlaceholder",
                "如：30 分钟内完成退款判定与回单",
              )}
            />
          </Form.Item>
          <Form.Item
            name="business_domain"
            label={t("staffdeck.sopPanel.fieldDomain", "业务域（可选）")}
          >
            <Input
              placeholder={t(
                "staffdeck.sopPanel.domainPlaceholder",
                "如：客服 / 交付 / 财务",
              )}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 复制：搜索全租户他人 SOP，复制为本员工私有草稿 */}
      <Modal
        title={t("staffdeck.sopPanel.copyTitle", "从其他员工的 SOP 复制")}
        open={copyOpen}
        footer={null}
        width={640}
        destroyOnHidden
        onCancel={() => setCopyOpen(false)}
      >
        <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
          <Input
            value={copyKeyword}
            onChange={(e) => setCopyKeyword(e.target.value)}
            onPressEnter={() => void searchCopiable()}
            placeholder={t("staffdeck.sopPanel.copySearch", "按名称搜索全租户 SOP")}
          />
          <Button
            type="primary"
            loading={copyLoading}
            onClick={() => void searchCopiable()}
          >
            {t("staffdeck.sopPanel.copyFind", "搜索")}
          </Button>
        </Space.Compact>
        <List
          dataSource={copyResults}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t(
                  "staffdeck.sopPanel.copyEmpty",
                  "没有可复制的 SOP",
                )}
              />
            ),
          }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="copy"
                  size="small"
                  onClick={() => void duplicate(item)}
                >
                  {t("staffdeck.sopPanel.copyAction", "复制为本员工草稿")}
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={`${item.name} (v${item.version})`}
                description={item.goal || item.description}
              />
            </List.Item>
          )}
        />
      </Modal>

      {/* 画布编辑抽屉（仅管理端 Drawer 模式）：保存=存内容，发布并生效=升版本+自动绑定。
          工作台模式由 onOpenCanvas 导航到 /studio/:aid/sop/:sopId 下钻页，不再弹窗。 */}
      {onOpenCanvas ? null : (
      <Drawer
        title={
          editingSop
            ? `${t("staffdeck.canvas.editorTitle", "SOP 画布编辑")} · ${editingSop.name} (v${editingSop.version})`
            : t("staffdeck.canvas.editorTitle", "SOP 画布编辑")
        }
        open={editingSop !== null}
        onClose={() => {
          setEditingSop(null);
          void refresh();
        }}
        width="94vw"
        destroyOnHidden
        styles={{ body: { padding: 12, height: "calc(100% - 55px)" } }}
        extra={
          <Popconfirm
            title={t(
              "staffdeck.sopPanel.publishConfirm",
              "发布将固化当前画布内容为新版本并对本员工生效？",
            )}
            onConfirm={async () => {
              if (!editingSop) {
                return;
              }
              await publish(editingSop.id);
              setEditingSop(null);
            }}
          >
            <Button type="primary" className="sd-btn-primary">
              {t("staffdeck.sopPanel.publish", "发布并生效")}
            </Button>
          </Popconfirm>
        }
      >
        {editingSop ? (
          <SopFlowCanvas
            sop={editingSop}
            onSave={async (payload) => {
              try {
                const updated = await sopApi.update(editingSop.id, {
                  nodes: payload.nodes,
                  edges: payload.edges,
                  slots: payload.slots,
                });
                setEditingSop(updated);
                message.success(t("staffdeck.canvas.saved", "已保存"));
              } catch (err) {
                message.error(String(err));
              }
            }}
          />
        ) : null}
      </Drawer>
      )}

      {/* 只读流程预览 */}
      <Drawer
        title={t("staffdeck.sop.preview", "SOP 流程预览")}
        open={previewSopId !== ""}
        onClose={() => setPreviewSopId("")}
        width={520}
        destroyOnHidden
      >
        {previewSopId ? <SopFlowPreview sopId={previewSopId} /> : null}
      </Drawer>

      {/* 版本历史：回滚=恢复快照并发布为新版本（审计优先，不改历史） */}
      <Drawer
        title={`${t("staffdeck.sopPanel.historyTitle", "版本历史")} · ${historySop?.name ?? ""}`}
        open={historySop !== null}
        onClose={() => setHistorySop(null)}
        width={560}
        destroyOnHidden
      >
        <Table
          rowKey="version"
          size="small"
          dataSource={versions}
          pagination={false}
          columns={[
            {
              title: t("staffdeck.sopPanel.colVersion", "版本"),
              dataIndex: "version",
              align: "center",
              render: (v: number) => `v${v}`,
            },
            {
              title: t("staffdeck.sopPanel.colNote", "说明"),
              dataIndex: "change_note",
              align: "center",
            },
            {
              title: t("staffdeck.sopPanel.colBy", "发布人"),
              dataIndex: "published_by",
              align: "center",
            },
            {
              title: t("staffdeck.sopPanel.colAt", "时间"),
              dataIndex: "created_at",
              align: "center",
              render: (v: string) => (v ?? "").slice(0, 16).replace("T", " "),
            },
            {
              title: t("staffdeck.sopPanel.colAction", "操作"),
              align: "center",
              render: (_: unknown, row: SopVersion) => (
                <Popconfirm
                  title={t(
                    "staffdeck.sopPanel.rollbackConfirm",
                    "回滚将恢复该版本内容到草稿，需员工发布后生效，确认？",
                  )}
                  onConfirm={() => void rollback(row.version)}
                >
                  <Button size="small">
                    {t("staffdeck.sopPanel.rollback", "回滚")}
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
