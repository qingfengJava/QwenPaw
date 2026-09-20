# -*- coding: utf-8 -*-
"""KB 检索评测集（T8）：60 组问答对（≥50 达标）。

每条 ``{"q": ..., "doc": index}``：query 必须由目标文档（DOCUMENTS
[index]）独占的专名或独有细节词构成，保证期望命中具有唯一可判性。
评测指标：Recall@5（期望文档出现在 top5 命中文档集合）与 MRR。

@author qingfeng
"""

from __future__ import annotations

#: 评测 QA 对（doc = corpus.DOCUMENTS 下标）
QA_PAIRS: list[dict[str, object]] = [
    # doc0 TravelCloud 差旅报销
    {"q": "TravelCloud 报销的提交时限是多少天", "doc": 0},
    {"q": "TravelCloud 里住宿费报销上限怎么算", "doc": 0},
    {"q": "TravelCloud 报销需要哪些发票材料", "doc": 0},
    {"q": "TravelCloud 出差补贴每天多少钱", "doc": 0},
    {"q": "TravelCloud 报销单被驳回后怎么重新提交", "doc": 0},
    # doc1 StarRing 保修
    {"q": "StarRing 机器人整机保修多长时间", "doc": 1},
    {"q": "StarRing 电池模组保修期多久", "doc": 1},
    {"q": "哪些情况不在 StarRing 保修范围内", "doc": 1},
    {"q": "StarRing Care 延保能延长到多少个月", "doc": 1},
    {"q": "StarRing 报修后多久上门维修", "doc": 1},
    # doc2 AuroraVPN
    {"q": "AuroraVPN 怎么登录", "doc": 2},
    {"q": "AuroraVPN 办公区和研发区隧道有什么区别", "doc": 2},
    {"q": "AuroraVPN 账号被锁定怎么办", "doc": 2},
    {"q": "公共 Wi-Fi 下必须挂 AuroraVPN 吗", "doc": 2},
    {"q": "海外出差用 AuroraVPN 哪个节点", "doc": 2},
    # doc3 BluewhaleCRM
    {"q": "BluewhaleCRM 客户分级 S 级标准是什么", "doc": 3},
    {"q": "BluewhaleCRM 分级多久重算一次", "doc": 3},
    {"q": "S 级客户在 BluewhaleCRM 享有哪些权益", "doc": 3},
    {"q": "BluewhaleCRM 客户投诉多久升级组长", "doc": 3},
    {"q": "BluewhaleCRM 导出客户数据要谁审批", "doc": 3},
    # doc4 TianshuBI
    {"q": "TianshuBI 有哪四级权限", "doc": 4},
    {"q": "TianshuBI 手机号脱敏规则是什么", "doc": 4},
    {"q": "TianshuBI 脱敏豁免工单有效期多久", "doc": 4},
    {"q": "TianshuBI 报表分享链接默认多久过期", "doc": 4},
    {"q": "TianshuBI 查询超时和导出上限是多少", "doc": 4},
    # doc5 Flyingfish SLA
    {"q": "Flyingfish P1 故障响应时间是多少", "doc": 5},
    {"q": "Flyingfish P2 故障多久内解决", "doc": 5},
    {"q": "哪些算 Flyingfish 的 P1 故障", "doc": 5},
    {"q": "Flyingfish 工单 SLA 豁免怎么标记", "doc": 5},
    {"q": "SLA 达成率低会触发什么改进措施", "doc": 5},
    # doc6 XuanwuSec
    {"q": "XuanwuSec 漏洞严重度分哪几级", "doc": 6},
    {"q": "Critical 漏洞多少小时内修复", "doc": 6},
    {"q": "XuanwuSec 响应编队有哪些角色", "doc": 6},
    {"q": "报漏洞在 XuanwuSec 能拿多少积分", "doc": 6},
    {"q": "漏洞修复后的观察期是多久", "doc": 6},
    # doc7 ZhuqueRelease
    {"q": "ZhuqueRelease 灰度比例有哪几档", "doc": 7},
    {"q": "ZhuqueRelease 回滚触发条件是什么", "doc": 7},
    {"q": "ZhuqueRelease 回滚要多久完成", "doc": 7},
    {"q": "能不能在 ZhuqueRelease 发布单里带 DDL", "doc": 7},
    {"q": "周五晚上能走 ZhuqueRelease 发布吗", "doc": 7},
    # doc8 BaizeKB
    {"q": "BaizeKB 文档 published 前要经过什么状态", "doc": 8},
    {"q": "BaizeKB 的 domain 和 doc_type 字段怎么用", "doc": 8},
    {"q": "BaizeKB 冲突检测什么时候生成冲突单", "doc": 8},
    {"q": "Agent 怎么获得 BaizeKB 知识库的检索授权", "doc": 8},
    {"q": "BaizeKB 解绑知识库后立即生效吗", "doc": 8},
    # doc9 QilinFinance
    {"q": "QilinFinance 对账要在几个工作日内完成", "doc": 9},
    {"q": "QilinFinance 差异超过多少要登记差异单", "doc": 9},
    {"q": "QilinFinance 资损差异多少小时内垫付", "doc": 9},
    {"q": "QilinFinance 账期锁定后还能补录凭证吗", "doc": 9},
    {"q": "增值税专用发票认证抵扣期限是多久", "doc": 9},
    # doc10 QingluanMail
    {"q": "QingluanMail 签名模板包含哪五要素", "doc": 10},
    {"q": "QingluanMail 加密外发链接几天失效", "doc": 10},
    {"q": "QingluanMail 附件多大自动转云端链接", "doc": 10},
    {"q": "向竞对域名发信 QingluanMail 会怎样", "doc": 10},
    {"q": "离职员工邮箱 QingluanMail 怎么处理", "doc": 10},
    # doc11 PenglaiDR
    {"q": "PenglaiDR 灾备演练多久执行一次", "doc": 11},
    {"q": "PenglaiDR 的 RTO 和 RPO 目标是多少", "doc": 11},
    {"q": "PenglaiDR 演练覆盖哪三类场景", "doc": 11},
    {"q": "PenglaiDR 演练安排在什么时间段", "doc": 11},
    {"q": "RTO 连续不达标会触发什么整改", "doc": 11},
]
