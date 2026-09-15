# SOP 私有能力化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 SOP 从"租户共享资产库+多对多绑定"改造为"数字员工 1:1 私有能力"，在员工详情页能力资产 Tab 内闭环新建→画布编辑→发布生效→复制→版本回滚→停用/删除。

**Architecture:** 零 DDL。后端 `sops.owner_id` 语义收紧为归属员工 id；运行时注入链路（`expert_resource_bindings` → `TaskContract.sop_refs`，决策 D3）不动，仅由接口层新增防护保证一对一。前端新增 `ExpertSopPanel` 组件接管员工详情页 SOP 区块（从现有 CapabilitySection 中拆出，独立文件避免 ExpertDetailPage.tsx 继续膨胀）。

**Tech Stack:** FastAPI + SQLAlchemy async（PG）/ React 18 + antd 5 + @xyflow/react / pytest（integration，`QWENPAW_TEST_PG_DSN` 门控）。

**Spec:** `docs/superpowers/specs/2026-09-14-sop-employee-owned-capability-design.md`

## Global Constraints

- 零表结构变更（`sops` / `sop_versions` / `expert_resource_bindings` 不动）。
- `sops.owner_id` 新语义 = 归属员工 id；一份 SOP 只绑一个员工，复用只能复制副本。
- 集成测试数据一律 `captest_` 前缀显式 id，定点清理，禁止全表清空（本机测试库与开发库同库）。
- 后端注释禁止行尾注释；方法/类 Javadoc 作者 `qingfeng`。
- 前端所有用户文案走 `t(key, 中文fallback)`，新 key 同步补 `console/src/locales/zh.json` 与 `en.json`。
- 不切 Git 分支（在当前 `feature/agent_run_logs_20260908` 直接提交，提交信息 Conventional Commits）。
- 已发布 SOP 允许直接编辑内容（编辑不改 status、不升 version）；「发布」才 version+1 写快照。运行时读 `sops` 行当前内容，版本链仅作回滚/审计——此为私有能力语义，与旧"资产库审计"语义的有意偏差。

---

## 文件结构总览

| 动作 | 文件 | 职责 |
|---|---|---|
| Modify | `src/qwenpaw/app/experts/sops.py` | update 放宽 / delete 放开 status / list_sops 支持 full / 新增 duplicate_sop |
| Modify | `src/qwenpaw/app/experts/capability.py` | 新增 `ensure_binding`（发布自动绑定的原子写入） |
| Modify | `src/qwenpaw/app/experts/models.py` | SopCreateBody 补 owner_expert_id；新增 SopPublishBody / SopDuplicateBody |
| Modify | `src/qwenpaw/app/routers/admin/expert_capability.py` | create 透传 owner / list 补参 / publish 组合绑定 / 新 duplicate 端点 / delete 守卫 / resources PUT owner 防护 |
| Test | `tests/integration/test_enterprise_expert_capability.py` | 追加 store 层语义测试 |
| Modify | `console/src/api/modules/admin/expertCapability.ts` | sopApi：list 补参、create 补 owner、publish 补 body、新增 duplicate |
| Create | `console/src/components/sop/ExpertSopPanel.tsx` | 员工私有能力面板（列表卡片+新建+复制+画布+版本史+停用/删除） |
| Modify | `console/src/pages/Agents/manage/ExpertDetailPage.tsx` | CapabilitySection：sop 从 sections 移除，挂载点换成 ExpertSopPanel，删除旧 sop 专属代码 |
| Modify | `console/src/locales/zh.json`、`console/src/locales/en.json` | staffdeck.sopPanel.* 词条 |

---

### Task 1: 后端 SopStore 语义改造（update 放宽 / delete 放开 / list full / duplicate）

**Files:**
- Modify: `src/qwenpaw/app/experts/sops.py`（`update_sop` L165-175、`list_sops` L133-163、`delete_sop` L451-470、文件尾部新增方法）
- Test: `tests/integration/test_enterprise_expert_capability.py`（文件尾部追加）

**Interfaces:**
- Produces:
  - `SopStore.update_sop(...)`：published 可编辑（status/version 不变），仅 archived 拒绝
  - `SopStore.list_sops(status="", owner_id="", q="", full=False)`：`full=True` 返回含 nodes/edges/slots 的完整投影
  - `SopStore.duplicate_sop(sop_id, target_expert_id, new_sop_id=None) -> Optional[SopRecord]`：副本 draft、owner=target、不复制绑定
  - `SopStore.delete_sop(sop_id)`：不再限 draft（绑定守卫在 router 层）

- [ ] **Step 1: 写失败测试**

在 `tests/integration/test_enterprise_expert_capability.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_sop_private_semantics(enterprise_env):
    """SOP 私有能力化：published 可编辑、full 投影、duplicate、无绑定可删。"""
    from qwenpaw.app.experts.sops import get_sop_store

    store = get_sop_store()
    created = await store.create_sop(
        name="源流程",
        sop_id="captest_sop_priv",
        goal="原目标",
        nodes=[{"id": "n1", "title": "步骤一", "expected_outcome": "ok"}],
        slots=[{"key": "k1", "label": "槽位"}],
        owner_id="captest_expert_a",
    )
    assert created.status == "draft"
    assert created.owner_id == "captest_expert_a"

    # 发布后允许直接编辑内容：status 保持 published、version 不变
    published = await store.publish_sop("captest_sop_priv")
    assert published is not None and published.version == 2
    edited = await store.update_sop("captest_sop_priv", goal="新目标")
    assert edited is not None
    assert edited.goal == "新目标"
    assert edited.status == "published"
    assert edited.version == 2

    # full 投影带 nodes；light 投影 nodes 为空
    full_rows = await store.list_sops(owner_id="captest_expert_a", full=True)
    assert any(r.id == "captest_sop_priv" and r.nodes for r in full_rows)
    light_rows = await store.list_sops(owner_id="captest_expert_a")
    assert all(not r.nodes for r in light_rows)

    # duplicate：新行 draft、owner 归目标员工、内容一致、不复制绑定
    copy = await store.duplicate_sop(
        "captest_sop_priv",
        target_expert_id="captest_expert_b",
        new_sop_id="captest_sop_copy",
    )
    assert copy is not None
    assert copy.status == "draft"
    assert copy.version == 1
    assert copy.owner_id == "captest_expert_b"
    assert copy.name == "源流程"
    assert copy.goal == "新目标"
    assert [n["id"] for n in copy.nodes] == ["n1"]

    # delete：无绑定时 published 也可物理删（版本快照同删）
    assert await store.delete_sop("captest_sop_copy") is True
    assert await store.get_sop("captest_sop_copy") is None


@pytest.mark.asyncio
async def test_ensure_binding_idempotent(enterprise_env):
    """ensure_binding 重复调用只落一行（发布自动绑定的幂等底座）。"""
    from qwenpaw.app.experts.capability import get_capability_store

    cap = get_capability_store()
    await cap.ensure_binding(
        "captest_expert_e", "sop", "captest_sop_e", {"name": "x"},
    )
    await cap.ensure_binding(
        "captest_expert_e", "sop", "captest_sop_e", {"name": "x"},
    )
    bindings = await cap.list_bindings("captest_expert_e", "sop")
    assert len([b for b in bindings if b.resource_id == "captest_sop_e"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:QWENPAW_TEST_PG_DSN = "<本机测试库 DSN，与开发库同库，取值见项目记忆/本地配置>"
python -m pytest tests/integration/test_enterprise_expert_capability.py -k "sop_private_semantics or ensure_binding" -v
```
预期：FAIL（`duplicate_sop` / `ensure_binding` 无此属性；update_sop published 抛 ValueError）。

- [ ] **Step 3: 实现 sops.py 改动**

3a. `update_sop` 状态守卫（L174-175）替换——published 不再拒绝，仅 archived 拒绝，并更新 docstring：

```python
    async def update_sop(self, sop_id: str, **fields) -> Optional[SopRecord]:
        """Update content fields (private-capability semantics).

        员工私有 SOP：published 也允许直接改内容（不改 status、不升
        version），运行时读行现值即刻生效；「发布」才升版本写快照。
        仅 archived 拒绝编辑（归档=终态）。
        """
        current = await self.get_sop(sop_id)
        if current is None:
            return None
        if current.status == SOP_STATUS_ARCHIVED:
            raise ValueError("archived SOPs cannot be edited")
```

3b. `list_sops` 签名与投影（L133-163）：

```python
    async def list_sops(
        self,
        status: str = "",
        owner_id: str = "",
        q: str = "",
        full: bool = False,
    ) -> List[SopRecord]:
        """List SOPs (light projection by default; full for owner panels)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid"]
        params: Dict[str, object] = {"tid": current_tenant_id()}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if owner_id:
            clauses.append("owner_id = :owner")
            params["owner"] = owner_id
        if q:
            clauses.append("(name ILIKE :kw OR description ILIKE :kw)")
            params["kw"] = f"%{q}%"
        cols = _COLS if full else _LIGHT_COLS
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + cols + " FROM sops WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC"
                ),
                params,
            )
            return [_row_to_sop(r, light=not full) for r in result]
```

3c. `delete_sop`（L451-470）去掉 status 条件（绑定守卫由 router 层承担）：

```python
    async def delete_sop(self, sop_id: str) -> bool:
        """Physical delete with version rows (router guards mounted SOPs)."""
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM sop_versions WHERE tenant_id = :tid "
                    "AND sop_id = :sid"
                ),
                {"tid": tid, "sid": sop_id},
            )
            result = await conn.execute(
                text(
                    "DELETE FROM sops WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": sop_id},
            )
            return result.rowcount > 0
```

3d. `SopStore` 类内新增 `duplicate_sop`（放 `archive_sop` 之前）：

```python
    async def duplicate_sop(
        self,
        sop_id: str,
        target_expert_id: str,
        new_sop_id: Optional[str] = None,
    ) -> Optional[SopRecord]:
        """Copy one SOP as a fresh draft owned by the target expert.

        复制式复用（用户决策）：副本是全新资产（新 id、draft、
        version=1），只复制业务内容，不复制绑定、不复制版本链。
        """
        source = await self.get_sop(sop_id)
        if source is None:
            return None
        return await self.create_sop(
            name=source.name,
            description=source.description,
            business_domain=source.business_domain,
            goal=source.goal,
            nodes=source.nodes,
            edges=source.edges,
            slots=source.slots,
            owner_id=target_expert_id,
            sop_id=new_sop_id,
        )
```

- [ ] **Step 4: 实现 capability.py 的 ensure_binding**

`src/qwenpaw/app/experts/capability.py`：文件头补 `import json`、`Optional` 导入（若缺）。`CapabilityStore` 类内 `replace_bindings` 之前新增：

```python
    async def ensure_binding(
        self,
        expert_id: str,
        resource_type: str,
        resource_id: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        """Insert one enabled binding if absent (publish auto-bind).

        发布组合动作的原子写入：ON CONFLICT DO NOTHING 保证幂等，
        不整表替换、不影响同员工其它类型绑定。
        """
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO expert_resource_bindings (tenant_id, "
                    "expert_id, resource_type, resource_id, enabled, seq, "
                    "metadata) VALUES (:tid, :eid, :rtype, :rid, TRUE, 0, "
                    "CAST(:meta AS JSONB)) ON CONFLICT DO NOTHING"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "rtype": resource_type,
                    "rid": resource_id,
                    "meta": json.dumps(metadata or {}),
                },
            )
```

- [ ] **Step 5: 跑测试确认通过**

```powershell
python -m pytest tests/integration/test_enterprise_expert_capability.py -k "sop_private_semantics or ensure_binding" -v
```
预期：2 PASSED。同时跑一遍存量 SOP 用例防回归：`-k "sop"` 全绿。

- [ ] **Step 6: Commit**

```powershell
git add src/qwenpaw/app/experts/sops.py src/qwenpaw/app/experts/capability.py tests/integration/test_enterprise_expert_capability.py
git commit -m "feat(sop): SopStore 私有能力化——published 可编辑、无绑定可删、full 投影、duplicate"
```

---

### Task 2: 后端路由接线（owner 透传 / publish 组合 / duplicate 端点 / 双守卫）

**Files:**
- Modify: `src/qwenpaw/app/experts/models.py`（SopCreateBody L390-397 附近）
- Modify: `src/qwenpaw/app/routers/admin/expert_capability.py`（L710-802 SOP 段、L351-405 resources 段）

**Interfaces:**
- Consumes: Task 1 的 `SopStore.duplicate_sop/list_sops(full=)`、`CapabilityStore.ensure_binding`
- Produces: REST 契约（Task 3 前端依赖）
  - `POST /admin/sops` body 增 `owner_expert_id?`
  - `GET /admin/sops?status=&q=&owner_id=&full=`
  - `POST /admin/sops/{id}/publish` body `{expert_id?}`（发布+自动绑定 owner/explicit 员工）
  - `POST /admin/sops/{id}/duplicate` body `{target_expert_id}` → 201 SopRecord
  - `DELETE /admin/sops/{id}`：仍被绑定 → 400
  - `PUT /admin/experts/{id}/resources`：新增非 owner 的 sop 绑定 → 400（存量豁免）

- [ ] **Step 1: models.py 补 body 模型**

`SopCreateBody` 追加字段（保持旧调用兼容）：

```python
class SopCreateBody(BaseModel):
    name: str
    description: str = ""
    business_domain: str = ""
    goal: str = ""
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    slots: List[Dict[str, Any]] = Field(default_factory=list)
    #: 归属员工 id（SOP 私有能力化：员工详情页新建时显式传入）
    owner_expert_id: Optional[str] = None


class SopPublishBody(BaseModel):
    """Publish payload; expert_id 指定时发布并自动绑定该员工（省略=用 owner）."""

    expert_id: Optional[str] = None


class SopDuplicateBody(BaseModel):
    """Copy source SOP as a fresh draft owned by target expert."""

    target_expert_id: str
```

- [ ] **Step 2: 路由改动（expert_capability.py）**

2a. import 块（L41-53）追加 `SopDuplicateBody`、`SopPublishBody`。

2b. `create_sop`（L716-728）owner 透传改为 body 优先：

```python
    return await get_sop_store().create_sop(
        name=body.name,
        description=body.description,
        business_domain=body.business_domain,
        goal=body.goal,
        nodes=body.nodes,
        edges=body.edges,
        slots=body.slots,
        owner_id=body.owner_expert_id or _actor(request),
    )
```

2c. `list_sops`（L710-713）补参数：

```python
@router.get("/sops", response_model=List[SopRecord])
async def list_sops(
    status: str = "",
    q: str = "",
    owner_id: str = "",
    full: bool = False,
) -> List[SopRecord]:
    """SOP assets (light projection; owner 面板用 full=true 取节点内容)."""
    return await get_sop_store().list_sops(
        status=status,
        q=q,
        owner_id=owner_id,
        full=full,
    )
```

2d. `publish_sop`（L762-771 现体）重写为"发布并生效"组合：

```python
@router.post("/sops/{sop_id}/publish", response_model=SopRecord)
async def publish_sop(
    sop_id: str,
    request: Request,
    body: Optional[SopPublishBody] = None,
) -> SopRecord:
    """Publish: version+1 + snapshot + auto-bind owner expert.

    私有能力化组合语义：发布成功后把 SOP 绑到归属员工（显式
    expert_id 优先，其次 owner_id），绑定已存在时幂等跳过；员工不
    存在（如历史资产的 owner 是用户名的旧数据）则只发布不绑定。
    """
    try:
        record = await get_sop_store().publish_sop(
            sop_id,
            published_by=_actor(request),
        )
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="SOP not found or archived")
    target = (body.expert_id if body else "") or record.owner_id or ""
    if not target:
        return record
    expert = await get_expert_store().get_expert(target)
    if expert is None:
        return record
    if record.owner_id and record.owner_id != target:
        raise HTTPException(
            status_code=400,
            detail="SOP is private to another expert; duplicate it to reuse",
        )
    await get_capability_store().ensure_binding(
        target,
        "sop",
        sop_id,
        {"name": record.name},
    )
    # 绑定变更同步草稿域 PROFILE（与 replace_resources 同一语义）
    try:
        from ...experts.preview import refresh_expert_preview_profile

        await refresh_expert_preview_profile(target, manager=_manager(request))
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "sop %s published+bound to %s but preview profile refresh failed",
            sop_id,
            target,
            exc_info=True,
        )
    return record
```

2e. `rollback_sop` 之后新增 duplicate 端点：

```python
@router.post("/sops/{sop_id}/duplicate", status_code=201, response_model=SopRecord)
async def duplicate_sop(sop_id: str, body: SopDuplicateBody) -> SopRecord:
    """复制式复用：任意 SOP 复制为目标员工的私有草稿（不复制绑定/版本链）."""
    await _require_expert(body.target_expert_id)
    record = await get_sop_store().duplicate_sop(
        sop_id,
        target_expert_id=body.target_expert_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Source SOP not found")
    return record
```

2f. `delete_sop`（L753-759）守卫从"仅草稿"改为"无绑定即可删"：

```python
@router.delete("/sops/{sop_id}", status_code=204)
async def delete_sop(sop_id: str) -> None:
    """无绑定的 SOP 可物理删；生效中的须先在员工页「停用」（解绑）."""
    mounted = await get_capability_store().list_experts_for_resource(
        "sop",
        sop_id,
    )
    if mounted:
        raise HTTPException(
            status_code=400,
            detail="SOP is still mounted; deactivate (unmount) before delete",
        )
    if not await get_sop_store().delete_sop(sop_id):
        raise HTTPException(status_code=404, detail="SOP not found")
```

2g. `replace_resources`（L351-405）循环内加 owner 防护（存量绑定豁免）。循环体之前插入：

```python
    existing_sop_ids = {
        b.resource_id
        for b in await get_capability_store().list_bindings(expert_id, "sop")
    }
```

循环体内 `if binding.resource_type == "sop"` 分支改为（复用一次 get_sop，消掉旧代码里只为填 name 的查询）：

```python
        if binding.resource_type == "sop":
            sop = await sop_store.get_sop(binding.resource_id)
            if sop is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"SOP {binding.resource_id} not found",
                )
            metadata.setdefault("name", sop.name)
            if (
                binding.resource_id not in existing_sop_ids
                and sop.owner_id
                and sop.owner_id != expert_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "SOP is private to another expert; "
                        "duplicate it to reuse"
                    ),
                )
```

- [ ] **Step 3: 快速回归**

```powershell
python -m pytest tests/integration/test_enterprise_expert_capability.py -k "sop" -v
python -m pytest tests/unit/app/test_workforce_sop_contract.py -v
```
预期：全绿（store 层未再变动；contract 注入不受影响）。

- [ ] **Step 4: 手工契约自测（后端起服 + curl 等价）**

见 Task 6 Step 2 的统一脚本，此任务只需确认进程能起、路由不报导入错：

```powershell
python -c "from qwenpaw.app.routers.admin.expert_capability import router; print(len(router.routes))"
```
预期：输出路由数量（含新增 duplicate 端点）。

- [ ] **Step 5: Commit**

```powershell
git add src/qwenpaw/app/experts/models.py src/qwenpaw/app/routers/admin/expert_capability.py
git commit -m "feat(sop): SOP 私有化路由——owner 透传、发布自动绑定、duplicate 端点、绑定一对一守卫"
```

---

### Task 3: 前端 API 客户端扩展

**Files:**
- Modify: `console/src/api/modules/admin/expertCapability.ts`（`sopApi` L377-437）

**Interfaces:**
- Consumes: Task 2 REST 契约
- Produces: `sopApi.list(status?, q?, ownerId?, full?)`、`sopApi.create({..., owner_expert_id})`、`sopApi.publish(sopId, expertId?)`、`sopApi.duplicate(sopId, targetExpertId)`（Task 4 依赖）

- [ ] **Step 1: 修改 sopApi**

```ts
  list: (status = "", q = "", ownerId = "", full = false) =>
    request<SopRecord[]>(
      `/admin/sops?status=${enc(status)}&q=${enc(q)}&owner_id=${enc(ownerId)}&full=${full}`,
    ),
```

`create` 的 body 类型追加可选字段 `owner_expert_id?: string;`（请求体直接 JSON.stringify，无需改实现）。

`publish` 与新增 `duplicate`：

```ts
  publish: (sopId: string, expertId = "") =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(expertId ? { expert_id: expertId } : {}),
    }),

  duplicate: (sopId: string, targetExpertId: string) =>
    request<SopRecord>(`/admin/sops/${enc(sopId)}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_expert_id: targetExpertId }),
    }),
```

注：若同文件其它 POST 未显式带 `Content-Type`（由 `request` 封装统一处理），则删去上述 headers 保持一致——动手前先看 `request` 封装。

- [ ] **Step 2: 类型检查**

```powershell
cd console; npx tsc -p tsconfig.app.json --noEmit
```
预期：0 error。

- [ ] **Step 3: Commit**

```powershell
git add console/src/api/modules/admin/expertCapability.ts
git commit -m "feat(sop): sopApi 客户端补 owner/full/publish-body/duplicate"
```

---

### Task 4: 新组件 ExpertSopPanel（员工私有 SOP 面板）

**Files:**
- Create: `console/src/components/sop/ExpertSopPanel.tsx`

**Interfaces:**
- Consumes: `sopApi`（Task 3）、`expertCapabilityApi.listResources/replaceResources`、`SopFlowCanvas`、`SopFlowPreview`、`StatusPill`
- Produces: `<ExpertSopPanel expertId={string} onChanged={async () => void} />`（Task 5 集成）

- [ ] **Step 1: 写完整组件**

```tsx
/**
 * sop/ExpertSopPanel.tsx — 员工私有 SOP 能力面板（SOP 私有能力化，20260914）。
 *
 * SOP 重定位为数字员工 1:1 私有能力：面板内闭环——新建（草稿）→
 * 画布编辑 → 发布并生效（后端自动绑定本员工）→ 从其他员工复制副本 →
 * 版本历史/回滚 → 停用（解绑）/ 删除。绑定关系仍是
 * expert_resource_bindings 权威（运行时 D3 注入链路不变）。
 */
import React, { useCallback, useEffect, useState } from "react";
import {
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
} from "@/api/modules/admin";

export function ExpertSopPanel({
  expertId,
  onChanged,
}: {
  expertId: string;
  /** 绑定/资产变更后回调（父级刷新计数与其余区块） */
  onChanged: () => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  // owner=本员工的全部 SOP（full 投影含节点）
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
  // 画布编辑 / 只读预览 / 版本历史 抽屉
  const [editingSop, setEditingSop] = useState<SopRecord | null>(null);
  const [previewSopId, setPreviewSopId] = useState("");
  const [historySop, setHistorySop] = useState<SopRecord | null>(null);
  const [versions, setVersions] = useState<
    Awaited<ReturnType<typeof sopApi.versions>>["versions"]
  >([]);

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

  /** 两态胶囊：生效中（published+绑定）/ 草稿 / 未生效（published 未绑定，历史遗留） */
  const statusOf = (sop: SopRecord) => {
    if (sop.status === "published" && boundIds.has(sop.id)) {
      return { tone: "green" as const, label: t("staffdeck.sopPanel.active", "生效中") };
    }
    if (sop.status === "draft") {
      return { tone: "blue" as const, label: t("staffdeck.sopPanel.draft", "草稿") };
    }
    return { tone: "amber" as const, label: t("staffdeck.sopPanel.inactive", "未生效") };
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
      message.success(t("staffdeck.sopPanel.deactivated", "已停用（不再注入任务规划）"));
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
      message.success(t("staffdeck.sopPanel.copied", "已复制为本员工草稿，请检查后发布"));
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
    if (!historySop) return;
    try {
      await sopApi.rollback(historySop.id, version);
      message.success(t("staffdeck.sopPanel.rolledBack", "已回滚并发布为新版本"));
      setVersions((await sopApi.versions(historySop.id)).versions ?? []);
      await refresh();
    } catch (err) {
      message.error(String(err));
    }
  };

  return (
    <div className="sd-card" style={{ padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sd-ink)" }}>
          {t("staffdeck.res.sop", "SOP 流程资产")}
        </span>
        <Space>
          <Button
            size="small"
            onClick={() => {
              setCreating(true);
              createForm.resetFields();
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

      {sops.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--sd-text-3)" }}>
          {t("staffdeck.sopPanel.empty", "尚无本员工的 SOP：新建流程沉淀经验，或从其他员工复制一份副本")}
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
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: "var(--sd-ink)" }}>
                    {sop.name}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--sd-text-3)" }}>
                    v{sop.version} · {(sop.nodes ?? []).length} {t("staffdeck.sopPanel.steps", "步骤")}
                    {" · "}
                    {(sop.slots ?? []).length} {t("staffdeck.sopPanel.slots", "槽位")}
                  </span>
                  <StatusPill tone={status.tone}>{status.label}</StatusPill>
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: "var(--sd-text-3)" }}>
                  {sop.goal || t("staffdeck.sopPanel.noGoal", "（未填总目标）")}
                </div>
                {sop.status === "draft" ? (
                  <div style={{ marginTop: 2, fontSize: 12, color: "var(--sd-amber, #d97706)" }}>
                    {t("staffdeck.sopPanel.draftHint", "草稿不生效，发布后注入任务规划")}
                  </div>
                ) : null}
                <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                  <Button size="small" type="primary" ghost onClick={() => setEditingSop(sop)}>
                    {t("staffdeck.sopPanel.canvasEdit", "画布编辑")}
                  </Button>
                  <Button size="small" onClick={() => setPreviewSopId(sop.id)}>
                    {t("staffdeck.res.view", "预览")}
                  </Button>
                  <Button size="small" onClick={() => void openHistory(sop)}>
                    {t("staffdeck.sopPanel.history", "版本历史")}
                  </Button>
                  {status.tone !== "blue" ? (
                    <Button size="small" className="sd-btn-primary" onClick={() => void publish(sop.id)}>
                      {t("staffdeck.sopPanel.publish", "发布并生效")}
                    </Button>
                  ) : null}
                  {mounted ? (
                    <Popconfirm
                      title={t("staffdeck.sopPanel.deactivateConfirm", "停用后本员工不再注入该流程，确认？")}
                      onConfirm={() => void unbind(sop.id)}
                    >
                      <Button size="small">{t("staffdeck.sopPanel.deactivate", "停用")}</Button>
                    </Popconfirm>
                  ) : (
                    <Popconfirm
                      title={t("staffdeck.sopPanel.deleteConfirm", "删除该 SOP（含版本历史）？")}
                      onConfirm={() => void remove(sop.id)}
                    >
                      <Button size="small" danger>{t("staffdeck.sopPanel.delete", "删除")}</Button>
                    </Popconfirm>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 新建：填基本信息后立即进入画布 */}
      <Modal
        title={t("staffdeck.sopPanel.createTitle", "新建 SOP")}
        open={creating}
        destroyOnHidden
        okText={t("staffdeck.sopPanel.createToCanvas", "创建并进入画布")}
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
            setEditingSop(created);
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
            rules={[{ required: true, message: t("staffdeck.sopPanel.nameRequired", "请填写流程名称") }]}
          >
            <Input placeholder={t("staffdeck.sopPanel.namePlaceholder", "如：售后退款处理流程")} />
          </Form.Item>
          <Form.Item name="goal" label={t("staffdeck.sopPanel.fieldGoal", "总目标（一句话）")}>
            <Input placeholder={t("staffdeck.sopPanel.goalPlaceholder", "如：30 分钟内完成退款判定与回单")} />
          </Form.Item>
          <Form.Item name="business_domain" label={t("staffdeck.sopPanel.fieldDomain", "业务域（可选）")}>
            <Input placeholder={t("staffdeck.sopPanel.domainPlaceholder", "如：客服 / 交付 / 财务")} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 复制：搜索全租户他人 SOP */}
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
          <Button type="primary" loading={copyLoading} onClick={() => void searchCopiable()}>
            {t("staffdeck.sopPanel.copyFind", "搜索")}
          </Button>
        </Space.Compact>
        <List
          dataSource={copyResults}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("staffdeck.sopPanel.copyEmpty", "没有可复制的 SOP")} /> }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button key="copy" size="small" onClick={() => void duplicate(item)}>
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

      {/* 画布编辑抽屉：保存=存内容，发布=升版本+自动生效 */}
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
            title={t("staffdeck.sopPanel.publishConfirm", "发布将固化当前画布内容为新版本并对本员工生效？")}
            onConfirm={async () => {
              if (!editingSop) return;
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

      {/* 版本历史：回滚=恢复快照并发布为新版本 */}
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
              render: (_: unknown, row: { version: number }) => (
                <Popconfirm
                  title={t("staffdeck.sopPanel.rollbackConfirm", `回滚到 v${row.version}（将发布为新版本）？`)}
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
```

- [ ] **Step 2: 类型检查**

```powershell
cd console; npx tsc -p tsconfig.app.json --noEmit
```
预期：0 error（`SopRecord.owner_id` 若类型缺失，回到 Task 3 在接口类型补 `owner_id?: string | null`）。

- [ ] **Step 3: Commit**

```powershell
git add console/src/components/sop/ExpertSopPanel.tsx
git commit -m "feat(sop): 新增 ExpertSopPanel 员工私有 SOP 面板（新建/发布/复制/版本史/停用/删除闭环）"
```

---

### Task 5: ExpertDetailPage 集成（替换旧 SOP 挂载区）

**Files:**
- Modify: `console/src/pages/Agents/manage/ExpertDetailPage.tsx`（CapabilitySection L875-1175）

**Interfaces:**
- Consumes: `ExpertSopPanel`（Task 4）
- Produces: 员工详情页「能力资产」Tab 的新 SOP 区块；旧 sop 挂载/预览/画布代码全部移除

- [ ] **Step 1: 改动 CapabilitySection**

1a. 删除本组件内 sop 专属状态与导入：`sops`/`setSops`、`previewSopId`、`editingSop` 三个 state；`SopFlowCanvas`、`SopFlowPreview`、`sopApi`、`SopRecord` 的 import（`adding` 联合类型去掉 `"sop"`；`sections` 数组删 `{ type: "sop", ... }` 项；`load` 里删 `setSops(await sopApi.list())`）。

1b. 在技能卡片（L932-947 的 sd-card）之后、`{sections.map(...)}` 之前插入：

```tsx
      {/* SOP 私有能力面板（SOP 私有能力化，20260914） */}
      <ExpertSopPanel
        expertId={expert.id}
        onChanged={async () => {
          await load();
          onChanged();
        }}
      />
```

1c. 挂载弹窗删除 `adding === "sop"` 分支（L1091-1103 的 Form.Item 与 L1054-1055、L1070-1077 中 sop 特判，kb/tool 逻辑保留，`resourceId` 统一取 `values.resource_id`、metadata 取 `values.name`）。

1d. 删除文件尾部本组件内的两个 SOP 抽屉（L1127-1172「SOP 只读流程图预览」「SOP 画布编辑器」）——已由 ExpertSopPanel 内部承载。

1e. 文件顶部 import 追加：

```tsx
import { ExpertSopPanel } from "@/components/sop/ExpertSopPanel";
```

- [ ] **Step 2: 全局残留检查**

```powershell
cd console; npx eslint src/pages/Agents/manage/ExpertDetailPage.tsx
```
预期：无 unused import / 变量告警。

- [ ] **Step 3: 构建验证**

```powershell
cd console; npm run build
```
预期：tsc + vite 构建成功。

- [ ] **Step 4: Commit**

```powershell
git add console/src/pages/Agents/manage/ExpertDetailPage.tsx
git commit -m "feat(sop): 员工详情页 SOP 区块换成私有能力面板，移除共享挂载交互"
```

---

### Task 6: i18n 词条 + 端到端自证

**Files:**
- Modify: `console/src/locales/zh.json`、`console/src/locales/en.json`（`staffdeck` 节点内新增 `sopPanel` 子对象）

**Interfaces:**
- Consumes: Task 4 的全部 t() key
- Produces: 中英文案完整（其余语言走中文 fallback，与现状一致）

- [ ] **Step 1: 补词条**

`zh.json` `staffdeck` 下新增（`en.json` 对应英文文案）：

```json
"sopPanel": {
  "active": "生效中",
  "draft": "草稿",
  "inactive": "未生效",
  "published": "已发布并生效",
  "publish": "发布并生效",
  "publishConfirm": "发布将固化当前画布内容为新版本并对本员工生效？",
  "deactivate": "停用",
  "deactivated": "已停用（不再注入任务规划）",
  "deactivateConfirm": "停用后本员工不再注入该流程，确认？",
  "delete": "删除",
  "deleted": "已删除",
  "deleteConfirm": "删除该 SOP（含版本历史）？",
  "create": "+ 新建 SOP",
  "createTitle": "新建 SOP",
  "createToCanvas": "创建并进入画布",
  "fieldName": "流程名称",
  "nameRequired": "请填写流程名称",
  "namePlaceholder": "如：售后退款处理流程",
  "fieldGoal": "总目标（一句话）",
  "goalPlaceholder": "如：30 分钟内完成退款判定与回单",
  "fieldDomain": "业务域（可选）",
  "domainPlaceholder": "如：客服 / 交付 / 财务",
  "copy": "从其他员工复制",
  "copyTitle": "从其他员工的 SOP 复制",
  "copySearch": "按名称搜索全租户 SOP",
  "copyFind": "搜索",
  "copyEmpty": "没有可复制的 SOP",
  "copyAction": "复制为本员工草稿",
  "copied": "已复制为本员工草稿，请检查后发布",
  "canvasEdit": "画布编辑",
  "history": "版本历史",
  "historyTitle": "版本历史",
  "colVersion": "版本",
  "colNote": "说明",
  "colBy": "发布人",
  "colAt": "时间",
  "colAction": "操作",
  "rollback": "回滚",
  "rollbackConfirm": "回滚将恢复该版本内容并发布为新版本，确认？",
  "rolledBack": "已回滚并发布为新版本",
  "steps": "步骤",
  "slots": "槽位",
  "noGoal": "（未填总目标）",
  "draftHint": "草稿不生效，发布后注入任务规划",
  "empty": "尚无本员工的 SOP：新建流程沉淀经验，或从其他员工复制一份副本"
}
```

- [ ] **Step 2: 起服务做契约 + UI 闭环自证**

按项目重启流程（后端 8088 / 前端 5173）：

```powershell
# 后端（仓库根）
python _run_backend.py   # 或既有启动方式
# 前端
cd console; npm run dev
```

契约面（PowerShell `Invoke-RestMethod` 或 curl，带 admin 会话头）：
1. `POST /api/admin/sops`（body 含 `owner_expert_id`）→ 201，`status=draft`、`owner_id` 为员工 id
2. `POST /api/admin/sops/{id}/publish`（body `{expert_id}`）→ `version=2`；`GET /api/admin/experts/{id}/resources` 的 sop 组出现该绑定
3. `GET /api/admin/sops?owner_id={id}&full=true` → 含 nodes
4. `POST /api/admin/sops/{id}/duplicate`（target=另一员工）→ 201 draft；目标员工 resources 无此绑定
5. 对非 owner 员工 `PUT resources` 新增该 sop 绑定 → 400 "private to another expert"
6. 有绑定时 `DELETE /api/admin/sops/{id}` → 400；停用（PUT 去掉绑定）后再删 → 204

UI 面（浏览器走一遍）：员工 A 详情页新建 SOP → 画布加 2 节点 → 发布并生效 → 卡片"生效中"；员工 B 详情页"从其他员工复制" → 复制 → 草稿卡片 → B 编辑发布 → A 侧内容不受影响；版本历史抽屉回滚一次成功；停用后计数条 SOP 数变化、删除按钮出现且可删。

- [ ] **Step 3: 回归**

```powershell
python -m pytest tests/integration/test_enterprise_expert_capability.py tests/unit/app/test_workforce_sop_contract.py -v
cd console; npm run build
```
预期：全绿。

- [ ] **Step 4: Commit**

```powershell
git add console/src/locales/zh.json console/src/locales/en.json
git commit -m "feat(sop): SOP 私有能力面板中英文词条"
```

---

## Self-Review 结论（已执行）

1. **Spec 覆盖**：§2 五动作流（新建/复制/编辑/版本史/停用删除）→ Task 4/5；§3.1 后端三项（duplicate/PUT 防护/publish 组合）→ Task 1/2；§3.2 前端两项 → Task 3/4/5；§3.3 存量兼容（豁免逻辑 + 不追溯）→ Task 2g；§四测试 → Task 1 测试 + Task 6 契约/UI 自证。无遗漏。
2. **占位符扫描**：唯一占位是测试 DSN（出于安全不写入计划，执行时从本地环境取）。
3. **类型一致性**：`duplicate_sop(sop_id, target_expert_id, new_sop_id)` store 层与 router 调用一致；`sopApi.publish(sopId, expertId)` 与 Task 2d `SopPublishBody.expert_id` 一致；`ensure_binding` 签名 Task 1/2 一致。
4. **有意偏差声明**：spec §2 步骤 3 的"发布仪式"落地为"编辑即刻生效（仅 owner 员工受影响）、发布=固化版本"——运行时读行现值的既有架构下，这是零表变更的最小实现，风险面从"误发布影响共享库"收窄为"仅影响 owner 自己员工"，与私有化定位自洽。
