# -*- coding: utf-8 -*-
"""write_audit helper 单测（T8）：字段透传 + best-effort 语义。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app import write_audit


class _FakeAuditLog:
    """记录 record 调用的审计后端替身。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, workspace_dir, tc_spec, decision) -> None:
        self.calls.append(
            {
                "workspace_dir": workspace_dir,
                "tool_name": tc_spec.tool_name,
                "target": tc_spec.target,
                "actor_id": tc_spec.user_id,
                "raw_params": tc_spec.raw_params,
                "reason": decision.reason,
            },
        )


@pytest.fixture()
def fake_log(monkeypatch):
    """注入替身审计后端（走 _audit_log 工厂，不触碰全局单例）。"""
    log = _FakeAuditLog()
    monkeypatch.setattr(write_audit, "_audit_log", lambda: log)
    return log


def test_record_write_audit_passes_fields(fake_log):
    """字段全量透传：tool_name/target/actor/before/after 落到 spec。"""
    write_audit.record_write_audit(
        tool_name="kb_review",
        target="kb1:doc1",
        actor_id="alice",
        before={"domain": "old"},
        after={"domain": "new"},
        reason="meta update",
    )
    assert len(fake_log.calls) == 1
    call = fake_log.calls[0]
    assert call["tool_name"] == "kb_review"
    assert call["target"] == "kb1:doc1"
    assert call["actor_id"] == "alice"
    assert call["raw_params"] == {
        "before": {"domain": "old"},
        "after": {"domain": "new"},
    }
    assert call["reason"] == "meta update"


def test_record_write_audit_defaults(fake_log):
    """缺省形状：before/after 空字典、actor 空、reason 兜底文案。"""
    write_audit.record_write_audit(tool_name="t", target="x")
    call = fake_log.calls[0]
    assert call["raw_params"] == {"before": {}, "after": {}}
    assert call["actor_id"] == ""
    assert call["reason"]


def test_record_write_audit_never_raises(monkeypatch):
    """审计后端异常只吞不抛（best-effort，绝不阻塞业务主流程）。"""

    def _boom():
        raise RuntimeError("backend down")

    monkeypatch.setattr(write_audit, "_audit_log", _boom)
    write_audit.record_write_audit(tool_name="t", target="x")
