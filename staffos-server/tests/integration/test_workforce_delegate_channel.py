# -*- coding: utf-8 -*-
"""Workforce 委派通道的真实 HTTP 自环测试（引擎"通电"验证）。

背景：workforce 全部 LLM 交互（委派/验收/规划/汇总）都经
``call_expert_text`` 的 HTTP 自环（POST /api/console/chat）。既有
引擎测试把 delegate/verify/call_expert_text 三个接缝整体 monkeypatch，
HTTP 自环零覆盖——曾因 base_url 缺 ``/api`` 前缀导致真实环境全部
委派 404 而测试全绿（"假绿"缺陷）。本文件用真实 uvicorn 服务端
（仅模拟 ``/api/console/chat`` 的 SSE 回执，不依赖任何模型）验证：

1. 基址归一化后请求路径必须是 ``/api/console/chat``
   （服务端只注册该路径：任何前缀回退都会 404 使测试失败）；
2. ``X-Agent-Id`` 头携带目标专家运行时标识；
3. SSE 帧解析与 ``turn_usage`` token 累计走真实解析路径；
4. ``delegate()`` 端到端：围栏 JSON → ResultContract + token_cost；
5. 非 2xx 回复按异常抛出（引擎按节点失败处理，不得静默吞掉）。

@author qingfeng
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 假 /api/console/chat 服务端（真实 TCP + 真实 HTTP，仅数据是脚本化的）
# ---------------------------------------------------------------------------


def _sse(*payloads: Dict[str, Any]) -> StreamingResponse:
    """把若干事件对象编码为 SSE 响应帧（data: <json>\\n\\n）。"""
    lines = "".join(
        f"data: {json.dumps(p, ensure_ascii=False)}\n\n" for p in payloads
    )
    return StreamingResponse(iter([lines]), media_type="text/event-stream")


def _message_event(text: str) -> Dict[str, Any]:
    """构造 /console/chat 的最终回执事件（extract_agent_text_content 适配）。"""
    return {
        "type": "message",
        "output": [
            {"role": "assistant", "content": [{"type": "text", "text": text}]}
        ],
    }


def _build_app(seen: List[Dict[str, Any]]) -> FastAPI:
    """构建只含 ``/api/console/chat`` 的最小服务端。

    故意不注册无 ``/api`` 前缀的 ``/console/chat``：被测代码若回退
    到未归一化基址，请求将 404 抛错——这正是要防的回归。

    按请求内容区分两种角色：委派（回 ResultContract JSON）与
    验收裁决（prompt 含"任务验收裁决"标记，回 verdict JSON）——
    verifier 通道与委派通道走同一 HTTP 自环，元组签名/解析契约
    必须一起锁定。
    """
    app = FastAPI()

    @app.post("/api/console/chat")
    async def fake_chat(request: Request):
        # 记录命中信息（路径断言 + 头断言的数据源）
        body = await request.json()
        seen.append(
            {
                "path": request.url.path,
                "agent_id": request.headers.get("X-Agent-Id", ""),
                "body": body,
            }
        )
        # 约定标记：X-Agent-Id=expert_fail_me → 500（非 2xx 异常路径）
        if seen[-1]["agent_id"] == "expert_fail_me":
            return StreamingResponse(iter(["boom"]), status_code=500)
        # 验收裁决角色：回结构化 verdict（PASS）
        if "任务验收裁决" in json.dumps(body, ensure_ascii=False):
            reply = (
                "验收完成。\n```json\n"
                '{"verdict": "PASS", "reason": "产出符合验收标准", '
                '"issues": [], "expected_change": [], "preserve": []}\n```'
            )
        else:
            # 委派角色：回 ResultContract JSON
            reply = (
                "好的，任务完成。\n```json\n"
                '{"status": "COMPLETED", "result_text": "前端方案正文", '
                '"decisions": ["采用响应式布局"], "confidence": 0.9}\n```'
            )
        return _sse(
            _message_event(reply),
            {"type": "turn_usage", "usage": {"total_tokens": 123}},
        )

    return app


@pytest.fixture
async def loopback_server():
    """在 127.0.0.1 随机端口启动真实 uvicorn 服务（线程内独立事件循环）。"""
    seen: List[Dict[str, Any]] = []
    config = uvicorn.Config(
        _build_app(seen), host="127.0.0.1", port=0, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # 等待监听就绪（拿到真实端口；超时直接失败避免悬挂）
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("loopback server failed to start")
        time.sleep(0.05)
    host, port = server.servers[0].sockets[0].getsockname()[:2]
    yield {"host": host, "port": port, "seen": seen}
    # 优雅关停并回收线程
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def last_api(loopback_server, monkeypatch):
    """把 read_last_api 指向自环服务（生产形态：host:port，无 /api 前缀）。"""
    from qwenpaw.agents.tools import agent_management as am

    monkeypatch.setattr(
        am,
        "read_last_api",
        lambda: (loopback_server["host"], loopback_server["port"]),
    )
    return loopback_server


# ---------------------------------------------------------------------------
# 1. 底层通道：call_expert_text
# ---------------------------------------------------------------------------


async def test_call_expert_text_hits_normalized_api_path(last_api):
    """自环必须命中 /api/console/chat（基址缺 /api 前缀的回归测试）。"""
    from qwenpaw.app.workforce.delegator import call_expert_text

    reply, session_id, tokens = await call_expert_text(
        "expert_demo", "请完成任务", session_id="sess_loop"
    )
    # 服务端只注册了 /api/console/chat：走到这里本身就证明前缀正确
    assert last_api["seen"], "自环请求未到达服务端"
    assert last_api["seen"][0]["path"] == "/api/console/chat"
    # 目标专家经 X-Agent-Id 头传递（既有收集器约定）
    assert last_api["seen"][0]["agent_id"] == "expert_demo"
    # SSE 回执文本与 usage token 走真实解析
    assert "任务完成" in reply
    assert tokens == 123
    assert session_id == "sess_loop"


async def test_call_expert_text_non_2xx_raises(last_api):
    """非 2xx 回复必须抛 HTTPStatusError（通道故障不得静默成空回复）。"""
    from qwenpaw.app.workforce.delegator import call_expert_text

    with pytest.raises(httpx.HTTPStatusError):
        await call_expert_text("expert_fail_me", "请完成任务")


# ---------------------------------------------------------------------------
# 2. 端到端：delegate() = 委派 + ResultContract 解析 + token 记账
# ---------------------------------------------------------------------------


async def test_delegate_returns_parsed_contract_with_tokens(last_api):
    """delegate 端到端：真实 HTTP 回执 → 围栏 JSON 解析 → token_cost。"""
    from qwenpaw.app.workforce.contracts import (
        RESULT_STATUS_COMPLETED,
        TaskContract,
    )
    from qwenpaw.app.workforce.delegator import delegate

    contract = TaskContract(
        task_id="task-1",
        objective="产出前端方案",
        expected_output=["结构化方案"],
    )
    result, session_id = await delegate("demo", contract, session_id="sess_d1")
    # 围栏 JSON 被解析为结构化字段
    assert result.status == RESULT_STATUS_COMPLETED
    assert result.result_text == "前端方案正文"
    assert result.decisions == ["采用响应式布局"]
    assert result.task_id == "task-1"
    # usage 事件累计写入 token_cost（run 级预算依据）
    assert result.token_cost == 123
    assert session_id == "sess_d1"
    # 委派 prompt 投影了任务契约（最小充分上下文，而非聊天记录）
    sent_body = last_api["seen"][0]["body"]
    prompt_text = json.dumps(sent_body, ensure_ascii=False)
    assert "产出前端方案" in prompt_text


async def test_verify_passes_over_real_channel(last_api):
    """verifier 走真实 HTTP 自环裁决 PASS——锁定验收通道的完整契约
    （call_expert_text 三元组解包 + verdict JSON 解析）。真实 E2E 曾
    暴露二元组解包让验收 100% ESCALATE 的缺陷（mock 桩互相掩盖）。"""
    from qwenpaw.app.workforce.contracts import (
        RESULT_STATUS_COMPLETED,
        ResultContract,
        RunPolicy,
        TaskContract,
        VERDICT_PASS,
    )
    from qwenpaw.app.workforce.verifier import verify

    contract = TaskContract(
        task_id="task-1",
        objective="产出前端方案",
        quality_criteria=["覆盖期望交付物"],
    )
    result = ResultContract(
        status=RESULT_STATUS_COMPLETED,
        result_text="前端方案正文",
    )
    verdict = await verify("lead", contract, result, RunPolicy())
    assert verdict.verdict == VERDICT_PASS
    assert "符合验收标准" in verdict.reason
    # 验收请求确实经过了归一化自环通道
    assert last_api["seen"][-1]["path"] == "/api/console/chat"
