# -*- coding: utf-8 -*-
"""Project feed SSE endpoint for XianWork real-time activity."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from ...enterprise import current_tenant_id
from ...events.bus import feed_topic, get_event_bus, now_ms
from ...projects.service import ProjectService, get_project_service
from .projects import _require_role

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/events",
    tags=["xian-feed-sse"],
)

#: Server-side keepalive so proxies do not close idle SSE streams.
_KEEPALIVE_S = 25.0


@router.get("")
async def feed_events(
    project_id: str,
    request: Request,
    last_event_id: str = Header(default="", alias="Last-Event-ID"),
    service: ProjectService = Depends(get_project_service),
) -> StreamingResponse:
    """SSE stream of one project's activity (auto-reconnect friendly)."""
    await _require_role(service, request, project_id, "")
    topic = feed_topic(current_tenant_id(), project_id)
    subscription = get_event_bus().subscribe(topic, last_event_id)

    async def generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        subscription.__anext__(),
                        timeout=_KEEPALIVE_S,
                    )
                except asyncio.TimeoutError:
                    yield f": keepalive {now_ms()}\n\n"
                    continue
                except StopAsyncIteration:
                    break
                payload = json.dumps(
                    {"event": event.data, "seq": event.seq},
                    ensure_ascii=False,
                    default=str,
                )
                yield f"id: {event.seq}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            subscription.close()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
