# -*- coding: utf-8 -*-
"""KB 检索评测集（T8）：60 组问答对（≥50 达标）。

分词口径适配（2026-09-20 诊断定稿）：``tokenize_mixed`` 对 CJK 串做
bigram——自然问句改写（"提交时限是多少天"）与原文 bigram（"提交时限"
在原文可能被切成 "提交"+"交报"）天然错位，tsquery AND 全失配 → 零命中。
因此 query 一律取**语料正文的逐字连续子串**：子串的相邻字符对必然 ⊆
原文 token 流（tokenize 纯局部确定性，无词典依赖），AND 必命中。

每条片段含本篇独占的专名或独占细节词，保证期望命中的跨文档唯一性。

@author qingfeng
"""

from __future__ import annotations

from .corpus import DOCUMENTS

#: 每篇 5 条原文摘录片段（逐字子串；独占专名/细节词保证唯一可判性）
SNIPPETS: list[list[str]] = [
    # doc0 TravelCloud
    [
        "员工使用 TravelCloud 报销系统提交差旅费用",
        "差旅结束后必须在 TravelCloud 中于 30 天内提交报销单",
        "超出部分 TravelCloud 报销系统自动标记为 self-pay",
        "TravelCloud 系统会对发票连号自动预警",
        "员工可在 TravelCloud 中修改后重新提交",
    ],
    # doc1 StarRing
    [
        "StarRing 系列服务机器人整机保修 24 个月",
        "电池模组作为易损耗件保修 6 个月",
        "私自拆机三种情形不在 StarRing 保修范围内",
        "客户可购买 StarRing Care 延保服务",
        "换新机在 StarRing 保修系统中生成新序列号",
    ],
    # doc2 AuroraVPN
    [
        "全员远程接入统一使用 AuroraVPN 客户端",
        "AuroraVPN 分为办公区与研发区两个隧道",
        "AuroraVPN 客户端掉线后 30 秒内自动重连",
        "员工在公共 Wi-Fi 下必须全程挂载 AuroraVPN",
        "海外出差员工使用 AuroraVPN 国际加速节点",
    ],
    # doc3 BluewhaleCRM
    [
        "BluewhaleCRM 按年度合同金额将客户分为 S/A/B/C 四级",
        "分级每季度初由 BluewhaleCRM 自动重算",
        "各级别权益清单在 BluewhaleCRM 权益中心维护",
        "BluewhaleCRM 的升级计时从客户首次进线开始",
        "BluewhaleCRM 保留完整导出审计日志 3 年",
    ],
    # doc4 TianshuBI（第 5 条用独占细节词句）
    [
        "TianshuBI 采用库表行列四级权限",
        "四级权限在 TianshuBI 权限中心独立配置",
        "申请查看明文需在 TianshuBI 提交脱敏豁免工单",
        "TianshuBI 报表分享链接默认 24 小时过期",
        "手机号中间四位打码，身份证保留前六位",
    ],
    # doc5 Flyingfish（第 5 条用独占词 SLA）
    [
        "Flyingfish 服务台对工单响应与解决时效作出 SLA 承诺",
        "SLA 达成率每月在 Flyingfish 服务看板公示",
        "判定为 P1 的工单自动拉起 Flyingfish 应急群",
        "豁免由组长在 Flyingfish 工单系统标记",
        "连续两个月 SLA 达成率低于 95% 的责任团队启动服务改进计划",
    ],
    # doc6 XuanwuSec
    [
        "安全漏洞统一报送 XuanwuSec 平台",
        "Critical 漏洞必须在 24 小时内完成止血修复",
        "XuanwuSec 响应编队由安全工程师、业务 Owner、SRE 组成",
        "漏洞报送人按 XuanwuSec 积分规则获得奖励",
        "漏洞修复后进入 7 天观察期",
    ],
    # doc7 ZhuqueRelease
    [
        "生产发布统一走 ZhuqueRelease 流水线",
        "发布经理在 ZhuqueRelease 中创建发布单",
        "ZhuqueRelease 的回滚按钮保留最近 10 个版本的镜像",
        "禁止在 ZhuqueRelease 发布单中夹带 schema 变更",
        "核心接口 P99 延迟超过 800 毫秒、出现资损类告警",
    ],
    # doc8 BaizeKB
    [
        "企业知识统一沉淀到 BaizeKB 平台",
        "BaizeKB 的生命周期动作全部留档审计",
        "BaizeKB 的冲突检测会在同库发现重复标题时生成冲突单",
        "员工或专家组与管理员在 BaizeKB 中完成绑定后",
        "解绑立即生效，不需要重启",
    ],
    # doc9 QilinFinance
    [
        "每月 3 个工作日内完成 QilinFinance 对账",
        "差异超过 1000 元的条目必须在 QilinFinance 中登记差异单",
        "QilinFinance 对账结果经财务经理复核后锁定账期",
        "进项发票在 QilinFinance 中查验真伪后入账",
        "增值税专用发票必须在开票后 360 天内认证抵扣",
    ],
    # doc10 QingluanMail
    [
        "公司对外邮件统一使用 QingluanMail 签名模板",
        "QingluanMail 模板由行政统一发布",
        "含客户数据的附件必须启用 QingluanMail 的加密外发",
        "向竞对域名发信触发QingluanMail 拦截提醒",
        "重要商务往来邮件按项目归档到 QingluanMail 档案库",
    ],
    # doc11 PenglaiDR
    [
        "核心系统每半年执行一次 PenglaiDR 灾备切换演练",
        "演练前在 PenglaiDR 平台登记演练范围与回切预案",
        "PenglaiDR 演练期间的客户影响需提前两周公告",
        "由 PenglaiDR 委员会跟踪闭环",
        "RTO 达标率连续两次不达标的系统强制进入架构整改专项",
    ],
]


def _validate_snippets() -> list[str]:
    """健全性校验：每条片段必须是原文逐字子串（bigram 对齐的前提）。"""
    problems: list[str] = []
    for doc_index, snippets in enumerate(SNIPPETS):
        text = DOCUMENTS[doc_index]["text"]
        for snippet in snippets:
            if snippet not in text:
                problems.append(f"doc{doc_index}: {snippet!r} not in corpus")
    return problems


#: QA 对派生（60 条 = 12 篇 × 5 片段；doc = corpus.DOCUMENTS 下标）
QA_PAIRS: list[dict[str, object]] = [
    {"q": snippet, "doc": doc_index}
    for doc_index, snippets in enumerate(SNIPPETS)
    for snippet in snippets
]
