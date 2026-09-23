# -*- coding: utf-8 -*-
"""Common third-party agent adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import (
    HarnessAttachment,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessDiscoveredMCPServer,
    HarnessModel,
    HarnessProvider,
)


class HarnessOperationNotSupportedError(RuntimeError):
    """Raised when a provider cannot perform a requested operation."""


# ---------------------------------------------------------------------------
# Harness Runtime Specification 协议 02/08：后端能力声明与生命周期回执
# ---------------------------------------------------------------------------

# 生命周期回执阶段：创建 → 启动 → 流式 → 停止/失败；
# checkpoint 的 saved 语义由 checkpoints 体系另行落库，不在此混用
RECEIPT_PHASE_CREATED = "created"
RECEIPT_PHASE_STARTED = "started"
RECEIPT_PHASE_STREAMING = "streaming"
RECEIPT_PHASE_STOPPED = "stopped"
RECEIPT_PHASE_FAILED = "failed"

RECEIPT_PHASES = (
    RECEIPT_PHASE_CREATED,
    RECEIPT_PHASE_STARTED,
    RECEIPT_PHASE_STREAMING,
    RECEIPT_PHASE_STOPPED,
    RECEIPT_PHASE_FAILED,
)


@dataclass(frozen=True)
class HarnessBackendCapabilities:
    """第三方后端能力声明（协议02/08：声明不等于验证）。

    逐 provider 显式声明结构化结果、取消、重连、usage 上报、工具治理
    与沙箱动作能力；未声明为 True 的能力不得承接对应任务，必须显式
    降级（只读/沙箱）或拒绝，不能以"声明已存在"代替真实测试。
    """

    #: 能按 ResultContract 语义返回结构化结果
    structured_result: bool = False
    #: 支持显式取消在途执行（取消后仍须核对副作用）
    cancellation: bool = False
    #: 断线/重启后可重连同一执行（不新建尝试）
    reconnect: bool = False
    #: 能上报真实 usage（False=消耗未知，账本不得按零结算）
    usage_reporting: bool = False
    #: 工具调用可被平台治理策略拦截（团队硬约束不被 off 模式短路）
    tool_governance: bool = False
    #: 宽动作工具运行于受限环境（出口可控）
    sandboxed_actions: bool = False
    #: 补充说明（如"仅支持只读命令"）
    notes: str = ""


@dataclass
class HarnessLifecycleReceipt:
    """生命周期回执（协议02/14）：执行标识先落库、后启动成员。

    ``usage_reported=False`` 表示用量未知（不计为零消耗）；账本消费
    时按来源去重，避免重复计费。
    """

    #: 本次子执行标识（与 TrustedExecutionEnvelope.execution_id 对应）
    execution_id: str
    #: 后端会话标识（重连依据）
    session_id: str = ""
    #: 当前阶段（RECEIPT_PHASES 之一）
    phase: str = RECEIPT_PHASE_CREATED
    #: 原始 usage 数据（provider 口径，由账本归一化）
    usage: dict[str, Any] = field(default_factory=dict)
    #: 是否携带真实 usage 采集
    usage_reported: bool = False
    #: 失败类别（phase=failed 时填写；瞬时/权限/参数/下游…）
    error_category: str = ""

    def is_terminal(self) -> bool:
        """回执是否处于关闭阶段（stopped/failed 才允许结算尝试）。"""
        # 只有明确的停止/失败阶段才算关闭
        return self.phase in (RECEIPT_PHASE_STOPPED, RECEIPT_PHASE_FAILED)


class HarnessAdapter(ABC):
    """Provider adapter used by the workspace harness runtime."""

    @property
    def capability_unavailable_message(self) -> str | None:
        """Explain why provider capability discovery is unavailable."""
        return None

    @abstractmethod
    async def status(self) -> HarnessProvider:
        """Return installation and authentication status."""

    @abstractmethod
    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Start a provider-owned login flow."""

    @abstractmethod
    async def logout(self) -> None:
        """Remove the provider-owned login."""

    async def models(self) -> list[HarnessModel]:
        """Return models available to the authenticated account."""
        return []

    async def history(self, session_id: str) -> list[HarnessHistoryItem]:
        """Return provider history for best-effort session recovery."""
        del session_id
        return []

    async def discover_mcp(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredMCPServer]:
        """Return read-only Provider-owned MCP configuration."""
        del cwd
        return []

    async def discover_skills(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredSkill]:
        """Return read-only Provider-owned Skills."""
        del cwd
        return []

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Run one provider-owned slash command."""
        del session_id, command, arguments, cwd, settings
        return [
            HarnessEvent(
                kind=HarnessEventKind.ERROR,
                text="This command is not supported by the backend.",
            ),
        ]

    async def reset_session(self, session_id: str) -> None:
        """Forget provider state associated with one QwenPaw session."""
        del session_id

    @abstractmethod
    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Run one turn and stream normalized events."""

    @abstractmethod
    async def stop(self) -> None:
        """Release provider processes and other resources."""


class MissingDependencyAdapter(HarnessAdapter):
    """Report an optional provider dependency without breaking startup."""

    def __init__(self, provider_id: str, provider_name: str) -> None:
        self._provider_id = provider_id
        self._provider_name = provider_name
        self._message = (
            f"Install qwenpaw[{provider_id}] to enable {provider_name}."
        )

    async def status(self) -> HarnessProvider:
        """Return an unavailable status with an actionable install hint."""
        return HarnessProvider(
            id=self._provider_id,
            name=self._provider_name,
            available=False,
            installed=False,
            error=self._message,
        )

    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Reject login until the provider dependency is installed."""
        del device_code
        raise RuntimeError(self._message)

    async def logout(self) -> None:
        """Reject logout until the provider dependency is installed."""
        raise RuntimeError(self._message)

    def run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Reject turns until the provider dependency is installed."""
        del session_id, prompt, cwd, settings, attachments

        async def unavailable_events() -> AsyncIterator[HarnessEvent]:
            if self._message:
                raise RuntimeError(self._message)
            yield HarnessEvent(kind=HarnessEventKind.ERROR)

        return unavailable_events()

    async def stop(self) -> None:
        """Release no resources for an unavailable provider."""


__all__ = [
    "HarnessAdapter",
    "HarnessBackendCapabilities",
    "HarnessLifecycleReceipt",
    "HarnessOperationNotSupportedError",
    "MissingDependencyAdapter",
]
