# -*- coding: utf-8 -*-
"""演示数据种子脚本：知识库 + 业务本体（企业示例数据，可重复执行）。

走产品管线造数（非裸 INSERT）：
- 知识库：``KbService.create_kb`` + ``pg_ingest_document`` 同步门面，
  复用真实摄入管线（切片/索引/wikilink 抽取），检索测试页开箱可搜；
- 本体：``ontology.service`` 全部操作置于**同一 asyncio 循环**执行
  （asyncpg 池绑定创建时 loop，跨 loop 复用会腐蚀——评测定稿教训），
  基于 T4 迁移已种入的 L1 业务类型建对象/关系/状态迁移/规则/动作，
  并用 ``kb_object_links`` 把知识文档挂到本体对象（知识↔本体互引）。

幂等性：KB 按空间名 + 文档 path、本体按 (type_id, name) 查重，
已存在即跳过；重复执行安全。

用法：
    .venv/Scripts/python.exe scripts/seed_demo_kb_ontology.py

@author qingfeng
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Windows 控制台 GBK 兜底：保证中文摘要输出不炸
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qwenpaw.app.kb.models import SCOPE_ORG  # noqa: E402
from qwenpaw.app.kb.service import get_kb_service  # noqa: E402
from qwenpaw.app.ontology import service as onto  # noqa: E402
from qwenpaw.app.ontology.models import (  # noqa: E402
    KbObjectLink,
    OntologyAction,
    OntologyObject,
    OntologyRelation,
    OntologyRule,
)

# ===========================================================================
# 一、知识库语料（3 个企业空间 × 3 篇文档，内容为可检索的真实业务文本）
# ===========================================================================

KB_SPACES = [
    ("产品知识库", "QwenPaw 平台产品文档：白皮书、配置指南与常见问题"),
    ("运维 SOP 库", "生产运维标准作业程序：部署回滚、备份恢复、告警响应"),
    ("研发制度库", "研发过程管理制度：代码评审、SQL 变更、故障复盘"),
]

KB_DOCS: dict[str, list[dict]] = {
    "产品知识库": [
        {
            "path": "product/whitepaper.md",
            "title": "QwenPaw 平台产品白皮书",
            "text": """# QwenPaw 平台产品白皮书

## 产品定位

QwenPaw 是面向企业的数字员工（Digital Employee）平台，把大模型能力封装为可持续运营的"数字员工"：每个数字员工拥有独立的档案、模型槽位、知识库绑定与工具权限，可以在工作台与真人协作，也可以通过 API 被业务系统调用。

## 核心能力

### 1. 数字员工运行时

数字员工以专家（expert）为单位建模，支持模型槽位三态配置（全局回退、专家覆盖、会话临时指定）、参数独立化与发布闸门。所有运行日志以 Span 形式落库，可在控制台回放完整执行树。

### 2. 企业知识库

知识库以空间（space）为单位组织文档，支持 Markdown 在线编辑与文件上传两种摄入方式。摄入管线自动完成切片、关键词与向量索引；检索采用混合策略，命中片段携带 kb_id + doc_id + chunk_id 溯源字段。知识库可以绑定到一个或多个数字员工，员工对话时即可引用库内知识（绑定即授权）。

### 3. 业务本体

本体层把企业要素建模为类型化对象（人员、部门、项目、产品、客户、合同等），对象之间通过带时效的有向关系连接，并支持状态机（状态迁移留档）、业务规则与动作定义。知识文档可通过互引表挂接到本体对象，实现"知识支撑对象"的图谱化检索。

## 部署形态

支持私有化部署与云端托管两种形态。私有化部署依赖 PostgreSQL 16+（含 pgvector 扩展），通过环境变量 QWENPAW_PG_DSN 指定连接串；存储后端由 QWENPAW_STORAGE_BACKEND 控制（json / pg / dual 三态）。控制台默认端口 8188。

## 版本演进

v1.x 完成数字员工运行时与聊天工作台；v2.0 引入企业 RBAC、组织架构与审计；v2.1 落地企业知识本体平台（Evidence/Wiki/Ontology 三层），并补齐检索质量评测门禁（Recall@5 ≥ 0.9）。
""",
        },
        {
            "path": "product/agent-config-guide.md",
            "title": "数字员工配置指南",
            "text": """# 数字员工配置指南

## 创建数字员工

进入「数字员工管理」页，点击新建：填写名称、角色定位与系统提示词。保存后系统会在专家台账建立记录，并自动完成与 agent.json 的身份对账（T14 机制，防止两侧漂移）。

## 模型槽位配置

每个数字员工有三个模型槽位：主模型、备模型、轻量模型。解析优先级为：会话临时指定 > 专家级覆盖 > 全局默认。槽位支持按提供商选择模型，API Key 在「模型提供商」页统一配置并加密落库，切换模型即时生效，无需重启。

## 参数覆盖

温度、top_p、最大输出长度等推理参数支持专家级独立覆盖；未覆盖的参数回退全局默认值。参数修改会生成新的档案版本，可随时回滚。

## 知识库绑定

在数字员工详情页的「知识库」区块，可以把一个或多个知识空间绑定给该员工。绑定时选择访问级别（只读/读写）。绑定后员工对话会自动检索绑定的知识库，把命中片段作为上下文引用，并标注来源文档。

## 发布流程

配置变更（提示词、模型、知识库绑定）首先落在草稿态，走「发布」闸门后对外生效。发布前系统会执行一致性校验：模型槽位是否可用、绑定知识库是否仍存在、提示词是否超过长度上限。

## 常见问题

员工无响应时优先检查：模型 API Key 是否有效、额度是否耗尽、知识库绑定是否指向已删除空间。运行日志页可以按 Span 逐层展开定位失败环节。
""",
        },
        {
            "path": "product/kb-faq.md",
            "title": "知识库使用常见问题 FAQ",
            "text": """# 知识库使用常见问题 FAQ

## 如何创建知识空间？

管理员进入「知识库管理」页，点击新建空间：填写名称与描述。空间按可见域分为个人（personal）、团队（team）、组织（org）、企业（enterprise）四档；管理页创建的空间默认组织域。

## 为什么刚上传的文档搜不到？

摄入是异步管线：上传后先建文档记录（状态 PROCESSING），切片与索引完成后转为 READY。一般几秒内完成；若长时间停在 PROCESSING，检查摄入日志中是否有解析器报错（如扫描件 PDF 需要额外 OCR 组件）。

## 检索不到预期内容怎么排查？

1. 用「检索测试」直接搜索文档里的原句片段（词面锚点），若原句都搜不到说明索引未就绪；
2. 检查查询词是否与文档用词差异过大，混合检索的关键词分支依赖词面重合；
3. 确认文档没有被 archive 归档，归档文档默认不参与检索。

## 数字员工怎么引用知识库？

先在员工详情页绑定知识空间，然后员工对话即可引用。注意安全语义：**绑定即授权**——未绑定该空间的员工调用检索工具不会返回任何片段（T10-S0 收敛语义，越权零泄漏）。

## 文档之间如何互链？

正文中使用 `[[目标路径]]` 语法可生成 wikilink 出边，例如 `[[product/whitepaper.md]]`。摄入时自动抽取链接关系，用于文档图谱展示。代码围栏内的 `[[...]]` 会被识别为语法示例，不产出真实链接。

## 如何下线一篇文档？

文档详情页选择「归档」（archive）：文档保留、停止参与检索。需要彻底删除时联系管理员在治理面板操作，删除会连带清理切片与索引。
""",
        },
    ],
    "运维 SOP 库": [
        {
            "path": "ops/deploy-rollback.md",
            "title": "服务部署与回滚 SOP",
            "text": """# 服务部署与回滚 SOP

## 适用范围

适用于 QwenPaw 后端服务与控制台前端的生产发布。发布窗口：工作日 14:00-17:00；周五 17:00 后禁止生产发布（见研发制度库《故障复盘管理制度》关联条款）。

## 发布前检查清单

1. CI 全绿：单元测试 + 契约测试 + 评测门禁（KB 检索 Recall@5 ≥ 0.9）全部通过；
2. 数据库变更已评审：对照 db 目录下 changelog 确认本次发布的全部 SQL 变更都已在预发库执行并验证；
3. 配置核对：新增环境变量（如 QWENPAW_PG_DSN、QWENPAW_STORAGE_BACKEND）已写入部署清单，禁止临场手敲；
4. 回滚方案确认：上一版本镜像 tag 与数据库快照点已记录在发布单。

## 标准发布流程

采用蓝绿部署：新版本先起绿组，健康检查（/health 连续 3 次 200 且启动日志无 ERROR）通过后，把流量从蓝组切到绿组；观察 30 分钟核心指标（错误率、P95 延迟、队列积压）无异常后下线蓝组。

## 回滚流程

发现严重问题（P0/P1）立即回滚，遵循"先恢复后定位"原则：

1. 流量切回蓝组（负载均衡一条命令完成，预估 2 分钟）；
2. 若数据库结构发生变更，按 changelog 逆序执行回滚脚本；加列类变更可保留（向后兼容），删列类变更必须回滚；
3. 回滚后在发布群同步：回滚时间、影响范围、初步原因假设；
4. 24 小时内补发复盘报告。

## 发布后观察

发布完成后值班工程师盯 2 小时：重点看慢 SQL 日志（阈值 500ms，超阈值输出 WARN 日志并携带 Mapper 方法全名）、agent 运行日志的错误 Span 占比、知识库摄入队列深度。
""",
        },
        {
            "path": "ops/pg-backup-restore.md",
            "title": "PostgreSQL 备份与恢复手册",
            "text": """# PostgreSQL 备份与恢复手册

## 备份策略

生产库每日 02:30 全量物理备份（pg_basebackup），WAL 归档持续开启，归档保留 14 天。备份完成后执行恢复演练校验（每月一次完整 PITR 演练，每季度跨机演练）。

## 逻辑备份（辅助）

结构与大表抽样使用 pg_dump 每周导出一次，保存到独立的备份存储（不与主库同宿主机）。逻辑备份用于误删单表的快速找回，不作为主恢复手段。

## 恢复流程（PITR）

1. 确认恢复目标时间点（RPO 内最近可用位点），停止应用写入（切维护页）；
2. 还原最近一次全量物理备份到临时实例；
3. 配置 recovery_target_time 后重放 WAL 到目标点；
4. 行数抽验：核心表（用户、会话、知识文档、本体对象）行数与备份前监控值比对；
5. 应用侧验证：登录、聊天、知识库检索三大链路冒烟；
6. 把临时实例提升为主库，恢复应用流量，全程目标 RTO < 60 分钟。

## 常见故障处理

**磁盘满**：优先清理 WAL 归档积压与日志表分区，禁止直接 DELETE 业务数据释放空间。**复制延迟突增**：检查网络吞吐与大事务，必要时临时提升复制并行度。**连接耗尽**：排查连接池泄漏（典型症状是 agent 运行日志中出现 timeout acquiring connection），先重启连接池占满的应用实例，再定位泄漏点。

## 环境变量约定

备份脚本依赖 QWENPAW_PG_DSN 获取连接串；未设置时脚本必须直接报错退出（fail-fast），禁止静默跳过造成"以为备份了其实没有"的假成功。
""",
        },
        {
            "path": "ops/alert-response.md",
            "title": "线上告警响应手册",
            "text": """# 线上告警响应手册

## 告警分级

- **P0**：核心链路不可用（登录失败率 > 50%、服务整体 5xx、数据库主库不可达）。响应时限 5 分钟，全员升级；
- **P1**：核心功能降级（知识库检索失败、数字员工无响应、发布回滚触发）。响应时限 15 分钟；
- **P2**：非核心异常（慢 SQL 超阈值、队列积压、磁盘水位 > 80%）。响应时限 2 小时，工作时间处理。

## 值班机制

值班按周轮换，值班工程师收到 P0/P1 告警后 5 分钟内在值班群确认接警；15 分钟内无法定位根因的，升级到模块 owner；30 分钟未恢复的，升级到技术负责人并考虑回滚。

## 处置动作速查

**数据库告警**：先看连接数与慢查询（pg_stat_activity），锁等待优先杀阻塞源头会话；**知识库摄入堆积**：看摄入队列深度与失败计数，失败文档可重摄重建（失败态不钉死）；**数字员工超时**：按 Span 执行树定位是模型调用慢还是工具调用挂起，模型侧超时先切备模型槽位。

## 升级路径

值班工程师 → 模块 owner（15 分钟）→ 技术负责人（30 分钟）→ 管理层（P0 超 1 小时）。每级升级必须附：当前现象、已排除项、下一步计划。

## 复盘要求

P0/P1 事件 48 小时内出复盘报告：时间线、根因、影响面、行动项（每条行动项必须有 owner 与截止日期）。复盘报告归档到研发制度库。
""",
        },
    ],
    "研发制度库": [
        {
            "path": "policy/code-review.md",
            "title": "代码评审规范",
            "text": """# 代码评审规范

## 分支模型

主干为 dev 分支，一切开发走 feature 分支（命名 feature/功能简述_日期），通过 PR 合入；禁止直接 push 到受保护分支。feature 分支必须从 dev 切出，合并方式使用 create a merge commit 保留分支历史，禁止 squash。

## PR 要求

1. 单个 PR 变更控制在 400 行以内（纯生成物、重构豁免可放宽）；
2. 提交信息遵循 Conventional Commits：feat/fix/refactor/test/docs/chore/perf 前缀 + 影响模块 + 简述；
3. PR 描述必须包含：变更动机、方案要点、验证方式（跑过哪些测试）；
4. 涉及数据库变更的 PR，必须同步包含 db 目录下的 changelog 与快照更新，缺一不合。

## 评审重点

按优先级：正确性（边界条件、并发、事务边界）→ 安全（注入、越权、密钥泄漏）→ 性能（N+1 查询、循环内单条查询、缓存穿透）→ 可维护性（命名、分层、重复代码）。风格问题交给 lint 工具，评审不纠结格式。

## 性能红线

列表接口禁止 N+1 查询；统计计数必须一次聚合查询完成；同一请求内相同语义的数据只查一次；慢 SQL 拦截器阈值 500ms，超阈值日志必须携带完整定位信息。

## 评审 SLA

PR 提交后 24 小时内完成首轮评审；阻塞意见（must fix）与建议意见（nice to have）必须明确区分；作者对每条意见回复"已修改/不修改+理由"，不允许已读不回。
""",
        },
        {
            "path": "policy/sql-change.md",
            "title": "SQL 变更管理规范",
            "text": """# SQL 变更管理规范

## 目录结构

所有数据库变更文件统一放在 db 目录下，按分支组织：每个 feature 分支对应 db/feature/{分支名}/ 目录，内含 test.sql 与 prod.sql 两份完整快照，changelog 子目录存放按日期递增的增量变更文件。主干对应 db/dev/，上线时直接执行对应分支的 prod.sql 全量快照。

## changelog 规范

文件命名 NN_变更简述.sql（NN 为当日序号），文件头必须写变更说明、变更时间、变更人、适用环境、是否同步快照。每次往 changelog 新增文件，必须同步更新本分支的 test.sql 与 prod.sql 快照，保持"快照 = 全部历史变更的累积"这一不变式。

## 幂等性要求（强制）

所有变更必须可重复执行：建表用 CREATE TABLE IF NOT EXISTS；加列先判断列存在；插数据用 INSERT ... ON CONFLICT DO NOTHING 或 INSERT IGNORE；菜单类配置先 DELETE 后 INSERT。不能幂等的变更（如数据订正）必须在文件头标注"仅可执行一次"。

## 红线

1. prod 快照禁止无条件的 DROP TABLE 与 TRUNCATE，确需删除必须 IF EXISTS 并注释原因；
2. 禁止在 feature 分支把变更写入主干目录（合并时统一归档）；
3. 枚举字段新增取值，必须同步更新字段 COMMENT 与代码枚举定义，两侧一致才可合并；
4. 核心业务表必须带 create_time / update_time 两个基础字段与逻辑删除位。

## AI 助手协作约定

AI 生成 SQL 变更前必须先确认当前 Git 分支，按分支映射规则落文件路径；禁止凭经验猜测目录。合并前检查清单包含"代码已合但 SQL 遗漏"专项核对。
""",
        },
        {
            "path": "policy/incident-postmortem.md",
            "title": "故障复盘管理制度",
            "text": """# 故障复盘管理制度

## 复盘范围

所有 P0/P1 故障必须复盘；同类 P2 故障一个月内发生 3 次以上的，升级为必须复盘项。复盘目的是改进系统而非追责个人，聚焦"为什么系统允许了这个故障发生"。

## 时间线还原

复盘报告必须包含精确到分钟的时间线：故障发生、告警触发、接警确认、定位进展、恢复动作、服务恢复。时间线数据以告警系统与发布记录为准，不依赖个人记忆。

## 根因分析方法

采用五问法（5 Whys）追问到系统性原因。每层原因区分：直接原因（什么坏了）、触发条件（什么引爆）、系统缺陷（为什么没拦住）。修复行动项对应系统缺陷层，直接原因层的修复只能算止血。

## 行动项管理

每条行动项必须有：负责人、截止日期、验证方式。行动项超期一周未闭环的，在周会通报并升级。行动项类型分布要求：至少一半是自动化/防御性改进（新增测试、告警、熔断），避免"多加小心"这类不可执行项。

## 知识沉淀

复盘报告归档到研发制度库并挂接到业务本体：故障案例作为知识文档关联到对应的系统对象（服务、数据库、部署流程），后续同类故障发生时，值班工程师可以通过对象图谱快速找到历史案例与处置方案。

## 示例案例

2026-09 事故：控制台渠道接入固定 403。根因是专家 ACL 校验缺失 admin 兜底分支，触发条件是多角色用户身份重映射后命中空权限集，系统缺陷是权限解析失败时默认拒绝且无告警。改进项：权限解析空集告警 + ACL 单元测试补齐 + 发布前权限矩阵回归。
""",
        },
    ],
}

# 检索自检用例：(查询词, 期望命中的文档 path)
SEARCH_PROBES = [
    ("回滚流程 先恢复后定位", "ops/deploy-rollback.md"),
    ("QWENPAW_PG_DSN 连接串", "ops/pg-backup-restore.md"),
    ("绑定即授权 越权", "product/kb-faq.md"),
    ("五问法 根因", "policy/incident-postmortem.md"),
]

# ===========================================================================
# 二、业务本体示例数据（基于 T4 已种入的 L1 类型）
# ===========================================================================

#: L1 类型 id（T4 迁移种子，见 ontology_types 表）
T_PRODUCT = "l1.product"
T_PROJECT = "l1.project"
T_PERSON = "l1.person"
T_DEPARTMENT = "l1.department"
T_CUSTOMER = "l1.customer"
T_CONTRACT = "l1.contract"
T_SUPPLIER = "l1.supplier"
T_TEAM = "l1.team"

#: 对象定义：(type_id, name, aliases, attributes, state)
ONTOLOGY_OBJECTS = [
    (T_PRODUCT, "QwenPaw 数字员工平台", ["QwenPaw", "数字员工平台"],
     {"版本": "v2.1.0", "部署形态": "私有化/云端", "技术栈": "Python + React"},
     "已发布"),
    (T_PROJECT, "知识本体平台一期", ["本体平台", "T0-T8"],
     {"周期": "2026-09", "里程碑": "Evidence/Wiki/Ontology 三层 + 评测门禁"},
     "进行中"),
    (T_PROJECT, "cron 双台账收口专项", ["T13", "cron 收口"],
     {"周期": "2026-09", "范围": "任务台账停写与 DROP 收口"},
     "已交付"),
    (T_PERSON, "清风", ["项目负责人"],
     {"角色": "平台架构师", "职责": "总体方案与架构评审"}, "在职"),
    (T_PERSON, "李文博", [],
     {"角色": "后端工程师", "职责": "KB 摄入管线与检索"}, "在职"),
    (T_PERSON, "王思颖", [],
     {"角色": "前端工程师", "职责": "知识库与本体控制台页面"}, "在职"),
    (T_PERSON, "陈国栋", [],
     {"角色": "运维负责人", "职责": "部署、备份与值班"}, "在职"),
    (T_DEPARTMENT, "平台研发部", [],
     {"职能": "平台产品研发"}, ""),
    (T_DEPARTMENT, "质量保障部", [],
     {"职能": "测试与运维保障"}, ""),
    (T_CUSTOMER, "华信集团", ["华信"],
     {"行业": "金融", "对接人": "赵经理"}, "成交"),
    (T_CUSTOMER, "南航物流", ["南航"],
     {"行业": "物流", "对接人": "孙主管"}, "商机"),
    (T_CONTRACT, "华信集团一期建设合同", ["华信合同"],
     {"金额万元": 180, "期限": "12 个月", "验收节点": "3 期"},
     "履行中"),
    (T_SUPPLIER, "青云云服务", ["青云"],
     {"服务": "云主机与对象存储"}, "合作中"),
    (T_TEAM, "本体平台攻坚小组", ["攻坚小组"],
     {"成立": "2026-09", "目标": "知识本体平台一期交付"}, ""),
]

#: 关系定义：(type, from(type_id, name), to(type_id, name))
ONTOLOGY_RELATIONS = [
    ("member_of", (T_PERSON, "清风"), (T_DEPARTMENT, "平台研发部")),
    ("member_of", (T_PERSON, "李文博"), (T_DEPARTMENT, "平台研发部")),
    ("member_of", (T_PERSON, "王思颖"), (T_DEPARTMENT, "平台研发部")),
    ("member_of", (T_PERSON, "陈国栋"), (T_DEPARTMENT, "质量保障部")),
    ("leads", (T_PERSON, "清风"), (T_TEAM, "本体平台攻坚小组")),
    ("belongs_to", (T_TEAM, "本体平台攻坚小组"), (T_DEPARTMENT, "平台研发部")),
    ("owns", (T_DEPARTMENT, "平台研发部"), (T_PROJECT, "知识本体平台一期")),
    ("delivers_to", (T_PROJECT, "知识本体平台一期"), (T_CUSTOMER, "华信集团")),
    ("governs", (T_CONTRACT, "华信集团一期建设合同"),
     (T_PROJECT, "知识本体平台一期")),
    ("depends_on", (T_PROJECT, "知识本体平台一期"),
     (T_PRODUCT, "QwenPaw 数字员工平台")),
    ("supports", (T_SUPPLIER, "青云云服务"),
     (T_PRODUCT, "QwenPaw 数字员工平台")),
    ("pursues", (T_PRODUCT, "QwenPaw 数字员工平台"),
     (T_CUSTOMER, "南航物流")),
]

#: 状态迁移：(对象名, to_state, trigger, operator)
ONTOLOGY_TRANSITIONS = [
    ("知识本体平台一期", "进行中", "kickoff", "清风"),
    ("cron 双台账收口专项", "已交付", "acceptance", "清风"),
]

#: 业务规则：(名称, object_type, 优先级, 条件, then, else)
ONTOLOGY_RULES = [
    ("大额合同法务会签", T_CONTRACT, 1,
     {"field": "金额万元", "op": ">", "value": 100},
     {"require": ["法务会签", "分管副总审批"]}, {}),
    ("生产发布窗口限制", T_PROJECT, 2,
     {"window": "周五 17:00 后", "action": "deploy"},
     {"deny": True, "message": "周五 17:00 后禁止生产发布"},
     {"allow": True}),
    ("知识文档双人复核", "l1.knowledge", 3,
     {"doc_scope": "制度与 SOP 类"},
     {"require": ["作者外第二人复核"]}, {}),
]

#: 动作定义：(名称, object_type, 审批要求)
ONTOLOGY_ACTIONS = [
    ("发送项目验收通知", T_PROJECT,
     {"approval": "项目经理审批", "channel": ["邮件", "站内信"]}),
    ("合同盖章登记", T_CONTRACT,
     {"approval": "法务复核", "auditable": True}),
]

#: 知识↔本体互引：(空间名, 文档 path, 对象名, relation)
ONTOLOGY_LINKS = [
    ("产品知识库", "product/whitepaper.md",
     "QwenPaw 数字员工平台", "supports"),
    ("产品知识库", "product/agent-config-guide.md",
     "知识本体平台一期", "mentions"),
    ("运维 SOP 库", "ops/deploy-rollback.md",
     "知识本体平台一期", "supports"),
    ("研发制度库", "policy/sql-change.md",
     "cron 双台账收口专项", "mentions"),
    ("研发制度库", "policy/incident-postmortem.md",
     "QwenPaw 数字员工平台", "mentions"),
]


# ===========================================================================
# 三、知识库种子（同步门面，桥接 KbService 内部 bridge loop）
# ===========================================================================


def seed_knowledge_base() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """幂等创建演示空间与文档。

    Returns:
        (path 映射, 空间 id 映射)：前者为 {空间名: {path: doc_id}}
        （互引自检都要用），后者为 {空间名: space_id}。

    Raises:
        RuntimeError: 摄入管线返回 failed（失败态不静默）。
    """
    svc = get_kb_service()
    result: dict[str, dict[str, str]] = {}
    space_ids: dict[str, str] = {}
    existing_spaces = {kb.name: kb for kb in svc.list_kbs()}
    for space_name, description in KB_SPACES:
        kb = existing_spaces.get(space_name)
        if kb is None:
            kb = svc.create_kb(
                space_name,
                scope=SCOPE_ORG,
                org_id="default",
                description=description,
            )
            if kb is None:
                raise RuntimeError(f"create_kb failed: {space_name}")
            print(f"[kb] 空间已创建: {space_name} ({kb.id})")
        else:
            print(f"[kb] 空间已存在，跳过创建: {space_name} ({kb.id})")
        space_ids[space_name] = kb.id
        existing_docs = {
            doc.path: doc.id for doc in svc.pg_list_documents(kb.id)
        }
        result[space_name] = {}
        for spec in KB_DOCS[space_name]:
            path = spec["path"]
            if path in existing_docs:
                result[space_name][path] = existing_docs[path]
                print(f"[kb] 文档已存在，跳过: {path}")
                continue
            ingest = svc.pg_ingest_document(
                space_id=kb.id,
                title=spec["title"],
                path=path,
                content_md=spec["text"],
                source="manual",
                source_meta={"seeder": "seed_demo_kb_ontology"},
            )
            if ingest is None or ingest.status == "failed":
                raise RuntimeError(f"ingest failed: {space_name}/{path}")
            result[space_name][path] = ingest.doc_id
            print(f"[kb] 文档已摄入: {path} ({ingest.chunk_count} chunks)")
    return result, space_ids


def search_smoke(space_docs: dict[str, dict[str, str]]) -> int:
    """检索自检：探测查询应命中预期文档（词面锚点，应全中）。

    Returns:
        命中失败条数（0 = 全部通过）。
    """
    svc = get_kb_service()
    space_ids = {
        k.name: k.id for k in svc.list_kbs()
    }
    misses = 0
    for space_name, docs in space_docs.items():
        kb_id = space_ids.get(space_name, "")
        for query, expected_path in SEARCH_PROBES:
            if expected_path not in docs:
                continue
            expected_doc = docs[expected_path]
            hits = svc.search(kb_id, query, top_k=5)
            if any(
                getattr(chunk, "doc_id", "") == expected_doc
                for chunk, _score in hits
            ):
                print(f"[search] HIT  q={query!r} -> {expected_path}")
            else:
                misses += 1
                print(f"[search] MISS q={query!r}（期望 {expected_path}）")
    return misses


# ===========================================================================
# 四、本体种子（全部操作置于同一 asyncio 循环）
# ===========================================================================


async def seed_ontology(
    space_docs: dict[str, dict[str, str]],
    space_ids: dict[str, str],
) -> None:
    """幂等创建本体对象/关系/迁移/规则/动作/互引。

    Args:
        space_docs: ``seed_knowledge_base`` 的 path 映射。
        space_ids: ``seed_knowledge_base`` 的空间 id 映射。
    """
    existing = await onto.list_objects(limit=1000) or []
    by_key = {(o.type_id, o.name): o for o in existing}

    # 1. 对象（幂等：按 (type_id, name) 查重）
    obj_ids: dict[str, str] = {}
    for type_id, name, aliases, attributes, state in ONTOLOGY_OBJECTS:
        found = by_key.get((type_id, name))
        if found is not None:
            obj_ids[name] = found.id
            print(f"[onto] 对象已存在，跳过: {name}")
            continue
        created = await onto.create_object(OntologyObject(
            id="", type_id=type_id, name=name, aliases=aliases,
            attributes=attributes, state=state, org_id="default",
            owner_id="qingfeng",
        ))
        if created is None:
            raise RuntimeError(f"create_object failed: {name}")
        obj_ids[name] = created.id
        print(f"[onto] 对象已创建: {name} ({created.id})")

    # 2. 关系（幂等：按端点 + type 查重）
    existing_rels = await onto.list_relations(limit=1000) or []
    rel_keys = {
        (r.type, r.from_id, r.to_id) for r in existing_rels
    }
    for rel_type, (ft, fname), (tt, tname) in ONTOLOGY_RELATIONS:
        key = (rel_type, obj_ids[fname], obj_ids[tname])
        if key in rel_keys:
            print(f"[onto] 关系已存在，跳过: {fname} -{rel_type}-> {tname}")
            continue
        await onto.create_relation(OntologyRelation(
            id="", type=rel_type,
            from_type=ft, from_id=obj_ids[fname],
            to_type=tt, to_id=obj_ids[tname],
        ))
        print(f"[onto] 关系已创建: {fname} -{rel_type}-> {tname}")

    # 3. 状态迁移（幂等：state 已是目标值则跳过）
    for name, to_state, trigger, operator in ONTOLOGY_TRANSITIONS:
        obj = await onto.get_object(obj_ids[name])
        if obj is not None and obj.state == to_state:
            print(f"[onto] 状态已是 {to_state}，跳过迁移: {name}")
            continue
        await onto.apply_transition(
            obj_ids[name], to_state,
            trigger_type=trigger, operator=operator,
        )
        print(f"[onto] 状态迁移已留档: {name} → {to_state}")

    # 4. 规则 / 动作（留档型，按名称查重）
    existing_rules = await onto.list_rules(limit=500) or []
    rule_names = {r.name for r in existing_rules}
    for name, otype, priority, cond, then, els in ONTOLOGY_RULES:
        if name in rule_names:
            print(f"[onto] 规则已存在，跳过: {name}")
            continue
        await onto.create_rule(OntologyRule(
            id="", name=name, object_type=otype, priority=priority,
            conditions=cond, then_actions=then, else_actions=els,
        ))
        print(f"[onto] 规则已创建: {name}")

    existing_actions = await onto.list_actions(limit=500) or []
    action_names = {a.name for a in existing_actions}
    for name, otype, approval in ONTOLOGY_ACTIONS:
        if name in action_names:
            print(f"[onto] 动作已存在，跳过: {name}")
            continue
        await onto.create_action(OntologyAction(
            id="", name=name, object_type=otype,
            approval=approval,
        ))
        print(f"[onto] 动作已创建: {name}")

    # 5. 知识↔本体互引（幂等：按文档 + 对象查重）
    name_to_type = {name: t for t, name, *_ in ONTOLOGY_OBJECTS}
    existing_links = []
    for docs in space_docs.values():
        for path, doc_id in docs.items():
            links = await onto.list_links(document_id=doc_id) or []
            existing_links.extend(links)
    linked_pairs = {
        (l.kb_document_id, l.object_id) for l in existing_links
    }
    for space_name, path, obj_name, relation in ONTOLOGY_LINKS:
        doc_id = space_docs.get(space_name, {}).get(path, "")
        obj_id = obj_ids.get(obj_name, "")
        if not doc_id or not obj_id:
            print(f"[onto] 互引缺前置，跳过: {path} ↔ {obj_name}")
            continue
        if (doc_id, obj_id) in linked_pairs:
            print(f"[onto] 互引已存在，跳过: {path} ↔ {obj_name}")
            continue
        await onto.create_link(KbObjectLink(
            id="", kb_space_id=space_ids.get(space_name, ""),
            kb_document_id=doc_id,
            object_type=name_to_type.get(obj_name, "l1.object"),
            object_id=obj_id,
            relation=relation,
        ))
        print(f"[onto] 互引已创建: {path} ↔ {obj_name} ({relation})")


# ===========================================================================
# 五、入口
# ===========================================================================


def main() -> int:
    """执行完整种子流程并输出摘要。"""
    print("== 演示数据种子开始（知识库 + 业务本体）==")
    space_docs, space_ids = seed_knowledge_base()
    asyncio.run(seed_ontology(space_docs, space_ids))
    misses = search_smoke(space_docs)
    total_docs = sum(len(d) for d in space_docs.values())
    print(
        f"== 完成：{len(KB_SPACES)} 个空间 / {total_docs} 篇文档 / "
        f"{len(ONTOLOGY_OBJECTS)} 个本体对象 / "
        f"{len(ONTOLOGY_LINKS)} 条知识互引 / "
        f"检索自检 miss={misses} =="
    )
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
