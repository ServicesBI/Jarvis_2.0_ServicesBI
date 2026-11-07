"""Canal SSE compativel com as notificacoes do cockpit e do desktop pet."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/api", tags=["notifications"])


class NotificationBroker:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, object]]] = set()

    async def publish(self, event: dict[str, object]) -> None:
        for queue in tuple(self._clients):
            await queue.put(event)

    async def stream(self) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=50)
        self._clients.add(queue)
        try:
            yield b'data: {"type":"connected"}\n\n'
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {payload}\n\n".encode("utf-8")
                except TimeoutError:
                    yield b": keepalive\n\n"
        finally:
            self._clients.discard(queue)


@router.get("/notifications")
async def notifications(request: Request) -> StreamingResponse:
    broker: NotificationBroker = request.app.state.notification_broker
    return StreamingResponse(
        broker.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
