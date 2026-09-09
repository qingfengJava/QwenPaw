# -*- coding: utf-8 -*-
"""Run-log lifecycle hooks.

A PRE_EXECUTE / FINALLY hook pair that records every chat run into the
run-log infrastructure:

* ``inbox_trace_store`` — per-run detail file (meta + session-delta events);
* ``run_log_store``     — append-only JSONL index powering the list API.

Mirrors :mod:`langfuse_hook`: run-scoped state travels through
``ctx.extras`` and every failure is logged and swallowed — run logging
must never break the conversation itself.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)

_RUNLOG_CTX_KEY = "_qp_runlog_ctx"

# Draft instances (workbench debug) carry a ``__draft`` agent-id suffix.
_DRAFT_SUFFIX = "__draft"


def _resolve_environment(agent_id: str | None) -> str:
    """Map the agent id to the display environment (online / debug)."""
    if agent_id and agent_id.endswith(_DRAFT_SUFFIX):
        return "debug"
    return "online"


def _read_agent_labels(ctx: HookContext) -> tuple[str, str]:
    """Return ``(agent_version, model)`` advertised by the agent config."""
    config = getattr(ctx, "agent_config", None)
    agent_version = (getattr(config, "version", "") or "")[:32]
    active_model = getattr(config, "active_model", None)
    model = getattr(active_model, "model", "") or ""
    return agent_version, model


def _peek_staged_usage(session_id: str) -> dict | None:
    """Non-destructive look at the staged LLM usage for this session.

    The channel layer persists (and pops) this record only after the
    runner finishes, so the FINALLY hook must peek instead of pop.
    """
    try:
        from ...token_usage.model_wrapper import TokenRecordingModelWrapper

        return TokenRecordingModelWrapper.peek_usage_for_session(session_id)
    except Exception:  # pylint: disable=broad-except
        return None


def _sum_delta_tokens(delta: list[dict]) -> int:
    """Sum ``qwenpaw_turn_usage`` totals across the session delta."""
    total = 0
    for msg in delta:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata")
        if not isinstance(metadata, dict):
            continue
        payload = metadata.get("qwenpaw_turn_usage")
        if not isinstance(payload, dict):
            continue
        usage = payload.get("usage")
        if isinstance(usage, dict):
            total += int(usage.get("total_tokens", 0) or 0)
    return total


class RunLogStartHook(LifecycleHook):
    """Open the run trace + index row before agent execution."""

    phase = Phase.PRE_EXECUTE
    name = "run_log_start"
    # Right after LangfuseTraceHook(12): same metadata assumptions, and
    # before BootstrapHook(20) which mutates messages.
    priority = 13

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            from ...runtime.message_convert import _get_last_user_text

            from ...app.inbox_trace_store import (
                create_trace,
                read_session_messages,
            )
            from ...app.run_log_store import append_run_index
            from ...__version__ import __version__

            run_id = uuid.uuid4().hex
            started_at = time.time()
            user_id = getattr(ctx.request, "user_id", None) or ""
            channel = getattr(ctx.request, "channel", None) or ""
            chat_id = getattr(ctx.request, "chat_id", None) or ""
            environment = _resolve_environment(ctx.agent_id)
            agent_version, model = _read_agent_labels(ctx)

            # Baseline snapshot: only messages created during this run
            # become trace events (same technique as the cron executor).
            baseline = await read_session_messages(
                runner=ctx.workspace,
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
            )

            await create_trace(
                run_id,
                meta={
                    "source": "chat",
                    "session_id": ctx.session_id,
                    "root_session_id": ctx.root_session_id,
                    "agent_id": ctx.agent_id,
                    "user_id": user_id,
                    "channel": channel,
                    "environment": environment,
                    "query": _get_last_user_text(ctx.input_msgs),
                    "model": model,
                    "version": agent_version,
                    "app_version": __version__,
                },
            )
            await append_run_index(
                {
                    "run_id": run_id,
                    "agent_id": ctx.agent_id,
                    "session_id": ctx.session_id,
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "channel": channel,
                    "source": "chat",
                    "environment": environment,
                    "query_preview": _get_last_user_text(ctx.input_msgs) or "",
                    "status": "running",
                    "started_at": started_at,
                    "finished_at": None,
                    "duration_ms": None,
                    "total_tokens": 0,
                    "model": model,
                    "version": agent_version,
                    "app_version": __version__,
                    "error": None,
                },
            )
            ctx.extras[_RUNLOG_CTX_KEY] = {
                "run_id": run_id,
                "baseline_count": len(baseline),
                "started_at": started_at,
            }

            # PG span path: open agent_runs + bind the run context so the
            # SpanRecorderMiddleware tags spans with this run. File-era
            # stores above stay untouched (they serve non-PG deployments).
            try:
                from ...app.run_log_pg_store import pg_available
                from ...observability.span_sink import (
                    get_span_sink,
                    set_run_context,
                )

                if pg_available():
                    get_span_sink().start_run(
                        {
                            "run_id": run_id,
                            "agent_id": ctx.agent_id or "default",
                            # Human-readable agent name for the run-log UI.
                            "display_name": (
                                getattr(ctx.agent_config, "name", None)
                                or None
                            ),
                            "session_id": ctx.session_id,
                            "root_session_id": ctx.root_session_id,
                            "chat_id": chat_id or None,
                            "user_id": user_id or None,
                            "channel": channel or None,
                            "source": "chat",
                            "environment": environment,
                            "query_preview": (
                                _get_last_user_text(ctx.input_msgs) or None
                            ),
                            "started_at": started_at,
                            "model": model or None,
                            "version": agent_version or None,
                            "app_version": __version__,
                        },
                    )
                    set_run_context(run_id)
            except Exception:  # pylint: disable=broad-except
                logger.warning("run log pg start failed", exc_info=True)
        except Exception:  # pylint: disable=broad-except
            logger.warning("run log start hook failed", exc_info=True)
        return HookResult()


class RunLogFinishHook(LifecycleHook):
    """Append session delta, finalize trace and close the index row."""

    phase = Phase.FINALLY
    name = "run_log_finish"
    # After LangfuseTraceCleanupHook(50); independent of other cleanups.
    priority = 51

    async def run(self, ctx: HookContext) -> HookResult:
        data = ctx.extras.pop(_RUNLOG_CTX_KEY, None)
        if not isinstance(data, dict):
            return HookResult()
        try:
            from ...app.inbox_trace_store import (
                append_trace_from_session_delta,
                finalize_trace,
            )
            from ...app.run_log_store import update_run_index

            run_id = str(data.get("run_id") or "")
            baseline_count = int(data.get("baseline_count", 0) or 0)
            started_at = float(data.get("started_at", 0.0) or 0.0)
            if not run_id:
                return HookResult()

            user_id = getattr(ctx.request, "user_id", None) or ""
            channel = getattr(ctx.request, "channel", None) or ""
            status = "failed" if ctx.error is not None else "success"
            error = repr(ctx.error) if ctx.error is not None else None

            delta = await append_trace_from_session_delta(
                run_id=run_id,
                runner=ctx.workspace,
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                baseline_count=baseline_count,
            )
            finished_at = time.time()
            await finalize_trace(run_id, status=status, error=error)

            # The channel layer writes usage meta only after the runner
            # returns, so the delta scan below usually sees zero; prefer
            # the staged record (actual model + summed tokens) instead.
            staged = _peek_staged_usage(ctx.session_id)
            staged_tokens = 0
            staged_model = ""
            if isinstance(staged, dict):
                try:
                    staged_tokens = int(staged.get("total_tokens", 0) or 0)
                except (TypeError, ValueError):
                    staged_tokens = 0
                staged_model = str(staged.get("model_name") or "")

            updates: dict = {
                "status": status,
                "finished_at": finished_at,
                "duration_ms": int((finished_at - started_at) * 1000),
                "total_tokens": staged_tokens or _sum_delta_tokens(delta),
                "error": error,
            }
            # Fallback scenarios may switch models mid-run; trust the
            # actually-used model over the config prediction.
            if staged_model:
                updates["model"] = staged_model
            await update_run_index(
                run_id,
                run_day=date.fromtimestamp(started_at),
                **updates,
            )

            # PG span path: close agent_runs with the same authoritative
            # tokens/model as the file index row.
            try:
                from ...app.run_log_pg_store import pg_available
                from ...observability.span_sink import get_span_sink

                if pg_available():
                    get_span_sink().finish_run(
                        status=status,
                        finished_at=finished_at,
                        duration_ms=int((finished_at - started_at) * 1000),
                        total_tokens=staged_tokens or _sum_delta_tokens(delta),
                        model=staged_model or None,
                        error=error,
                    )
            except Exception:  # pylint: disable=broad-except
                logger.warning("run log pg finish failed", exc_info=True)
        except Exception:  # pylint: disable=broad-except
            logger.warning("run log finish hook failed", exc_info=True)
        finally:
            # Unbind the run context unconditionally (idempotent) so later
            # warmup calls cannot leak spans into a finished run.
            try:
                from ...observability.span_sink import clear_run_context

                clear_run_context()
            except Exception:  # pylint: disable=broad-except
                logger.debug("run log ctx clear failed", exc_info=True)
        return HookResult()


__all__ = ["RunLogFinishHook", "RunLogStartHook"]
