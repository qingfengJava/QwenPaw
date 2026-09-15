# SOP 私有能力化设计 —— 从共享资产库到员工私有流程能力

> 日期：2026-09-14　分支：`feature/agent_run_logs_20260908`　作者：清风
> 状态：已评审（用户确认方案：私有为主 + 复制式复用，禁止一份 SOP 绑定多个员工）
> 前序设计：`docs/design/2026-08-30-digital-employee-capability-layer.md`（决策 D3 运行时注入链路保持不变）

---

## 一、问题与定位

### 1.1 现状缺口

原设计中 SOP 是租户级共享资产（`sops` 表 + `expert_resource_bindings` 多对多绑定），
导致员工详情页「能力资产」Tab 的 SOP 区块是唯一"只能借、不能产"的能力块：

- 前端仅接了 `sopApi.list / get / update`，**`create / publish / rollback / archive /
  duplicate` 均无 UI 入口**；
- 挂载下拉只展示 `status === "published"` 的 SOP，而页面上无任何途径产生
  published SOP → 用户找不到操作位置，功能事实不可用。

### 1.2 重定位

**SOP 是数字员工的一项私有能力**，与记忆、定时任务同级：在员工详情页内自包含
闭环（新建 → 画布编辑 → 发布生效 → 版本回滚 → 停用/删除）。跨员工复用不采用
"绑同一份"，而是**复制一份一模一样的副本**归新员工所有，独立演化。

| 维度 | 旧模型（资产库+绑定） | 新模型（员工私有能力） |
|---|---|---|
| 归属 | 租户级共享，多员工绑同一份 | 一份 SOP 只属于一个员工（1:1，`sops.owner_id` = 员工 id） |
| 生产入口 | 无 UI（死锁根源） | 员工详情页内新建 |
| 复用 | 绑同一份资产 | 复制副本（新 id、归目标员工、状态=草稿） |
| 生效 | 已发布 + 绑定两步 | 发布即生效（绑定在发布动作内自动完成，用户无感知） |
| 可见状态 | draft/published/archived 三态 | 草稿（未生效）/ 生效中 两态；归档仅作删除过渡不在主界面露出 |

运行时不变：workforce 仍从 `expert_resource_bindings` 解析 `sop_refs` 注入规划与
验收 rubric（D3），只是绑定关系由接口校验收紧为一对一。

## 二、交互设计（员工详情页 SOP 区块）

区块从"绑定管理"改造为员工 SOP 列表，每张卡片一个 SOP：

- 卡片信息：名称、总目标（goal）、步骤数/槽位数、版本与状态胶囊（`v3 · 生效中` /
  `v1 · 草稿`）；草稿卡片带提示"草稿不生效，发布后注入任务规划"。
- 区块头两个动作：**[+ 新建 SOP]**、**[⧉ 从其他员工复制]**。

动作流：

1. **新建 SOP**：小弹窗填 名称/总目标/业务域 → `create`（owner=当前员工，草稿）→
   立即打开全屏 `SopFlowCanvas` 画布 → 画布内「保存草稿」+「发布并生效」；
   发布 = `publish`（version+1 写快照）+ 自动绑定当前员工，一次完成。
2. **从其他员工复制**：弹窗搜索全租户任意 SOP（`sopApi.list(q)`）→ 选中
   「复制为本员工的 SOP」→ 后端 duplicate 生成新 id 副本挂当前员工（草稿态，
   用户检查后自行发布）。
3. **画布编辑（生效中）**：编辑保存只改草稿内容（update 不动 status），
   必须再点「发布并生效」才升版本快照——保留发布仪式感，防误发布；
   重发布后所有页面自然读最新 published，对 owner 员工即时生效。
4. **版本历史**：抽屉展示 `sop_versions` 时间线（版本号/变更人/时间），
   每条支持「回滚为此版本」= 恢复快照并发布为新版本（审计优先，不改历史）。
5. **停用** = 解除绑定，SOP 行保留并回到草稿语义；**删除** 仅未生效
   （无绑定）的 SOP 可物理删，生效中的引导先停用。

知识库、工具区块维持现有"挂载"模式不变（天然共享引用型资源）。

## 三、数据与接口设计（零 DDL）

`sops` / `sop_versions` / `expert_resource_bindings` 表结构全部不动。
仅一处语义收紧：`sops.owner_id` 明确为**归属员工 id**。

### 3.1 后端改动

1. **新增** `POST /admin/sops/{sop_id}/duplicate`（body: `{target_expert_id}`）：
   事务内 复制源行全部业务字段 → 新行（id 新分配、owner_id=target、status=draft、
   version=1）→ 不自动绑定（副本以草稿呈现给目标员工，由用户检查后发布）。
   幂等：每次调用生成新副本，天然无冲突。
2. **防护** `PUT /{expert_id}/resources`：`resource_type='sop'` 时校验
   `sops.owner_id == expert_id`，不满足报 400——接口层封死"一份绑多个"。
3. **发布组合** `POST /admin/sops/{id}/publish`：publish 成功后若
   `owner_id` 非空且尚无绑定，自动写入 `expert_resource_bindings`
   （sop 行，enabled=true，metadata 快照名称）——前端"发布并生效"单按钮的支撑。
   （或保持 publish 纯净、前端顺序调用两接口；实施取**后端组合**，保证原子性。）

### 3.2 前端改动

- `sopApi` 客户端补 `duplicate` 方法；`create` 补 `owner_id` 入参透传。
- `ExpertDetailPage` 的 `CapabilitySection`：SOP 区块重写为员工 SOP 列表
  （数据源 = 本员工绑定 ∪ owner=本员工的行），移除"从库中选择 published 挂载"
  下拉（该入口对 sop 类型废弃，kb/tool 保留）；接入新建弹窗、复制弹窗、
  画布抽屉（已有）、版本历史抽屉（新组件，轻量表格）。

### 3.3 存量兼容

- 若存在旧的"一 SOP 绑多员工"数据：不改数据。UI 每个员工只展示
  owner=自己的 SOP；非 owner 的旧绑定仍可运行（兼容读），编辑入口仅 owner
  员工页显示；PUT 防护只拦截**新增**非 owner 绑定，不追溯拆存量。
- 演进提案 `target=sop`（归因缺陷 → 改 SOP → publish 新版本）链路不受影响，
  一对一后提案指向更明确。

## 四、测试要点

- 后端单测：duplicate（新行字段正确/owner 正确/不复制绑定）；publish 自动绑定
  （首次发布建绑定、重复发布不重建）；resources PUT 对非 owner SOP 报 400、
  owner 匹配放行。
- 前端：新建→草稿→编辑→发布→生效中状态流转；复制弹窗搜索与克隆后归属；
  版本历史回滚刷新。
- E2E（可选）：员工 A 建 SOP 并发布 → 员工 B 复制 → B 编辑发布 →
  A 的内容与版本链不受影响。

## 五、明确不做（YAGNI）

- 独立 SOP 库管理页（用户否决：SOP 是员工详情页内能力）；
- 私有分支 synced/diverged 与晋升机制（StaffDeck 重型方案）；
- 一份 SOP 多员工绑定（用户明确禁止）；
- 前端"归档"操作入口（archive 端点保留仅作删除过渡与审计）。
