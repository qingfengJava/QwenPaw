# -*- coding: utf-8 -*-
"""Bootstrap guidance hook.

Checks for BOOTSTRAP.md in the workspace and injects guidance into the
agent's system prompt for the first interaction.  The system prompt is
rebuilt per request and never persisted into ``state.context``, so the
session history keeps the user's original message.  Operates on
``ctx.agent`` — input messages are left untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class BootstrapHook(LifecycleHook):
    """Inject BOOTSTRAP.md guidance into the first turn's system prompt."""

    phase = Phase.PRE_EXECUTE
    name = "bootstrap"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.extras.get("is_cron"):
            return HookResult()

        wd = ctx.workspace_dir
        if not wd:
            return HookResult()

        bootstrap_path = Path(wd) / "BOOTSTRAP.md"
        bootstrap_completed_flag = Path(wd) / ".bootstrap_completed"

        if bootstrap_completed_flag.exists():
            return HookResult()
        if not bootstrap_path.exists():
            return HookResult()

        if not ctx.input_msgs:
            return HookResult()

        agent = ctx.agent
        if agent is None:
            return HookResult()

        try:
            from ...agents.prompt import build_bootstrap_guidance

            language = "zh"
            agent_config = ctx.agent_config
            if agent_config is not None:
                language = getattr(agent_config, "language", "zh") or "zh"

            bootstrap_guidance = build_bootstrap_guidance(language)

            # Append to the transient system prompt instead of prepending
            # to the user message: whatever is mutated in ``input_msgs``
            # is deep-copied into ``state.context`` by agentscope and
            # persisted with the session snapshot, so the guidance used
            # to echo back as part of the user's own message after a
            # refresh. The system prompt is rebuilt per request and never
            # persisted, so this guides the model without rewriting what
            # the user said.
            base_prompt = getattr(agent, "_system_prompt", "") or ""
            agent._system_prompt = (
                base_prompt.rstrip() + "\n\n" + bootstrap_guidance
            )

            bootstrap_completed_flag.touch()
            logger.debug("Bootstrap guidance injected into system prompt")
        except Exception:
            logger.debug("bootstrap: injection failed", exc_info=True)

        return HookResult()


__all__ = ["BootstrapHook"]
