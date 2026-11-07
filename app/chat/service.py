"""Orquestra o streaming sem conhecer HTTP ou provedores concretos."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest


DisconnectProbe = Callable[[], Awaitable[bool]]


class ChatService:
    """Encaminha pedidos a um executor injetável e preserva chunks textuais."""

    def __init__(self, executor: ChatExecutor) -> None:
        self.executor = executor

    async def stream(
        self,
        chat_request: ChatRequest,
        is_disconnected: DisconnectProbe,
    ) -> AsyncIterator[str]:
        iterator = self.executor.stream(chat_request)
        disconnect_notified = False

        try:
            while True:
                if await is_disconnected():
                    await self.executor.on_client_disconnect(chat_request)
                    disconnect_notified = True
                    return

                try:
                    chunk = await anext(iterator)
                except StopAsyncIteration:
                    return

                if await is_disconnected():
                    await self.executor.on_client_disconnect(chat_request)
                    disconnect_notified = True
                    return

                if chunk:
                    yield chunk
        except asyncio.CancelledError:
            if not disconnect_notified:
                await asyncio.shield(self.executor.on_client_disconnect(chat_request))
            raise
        except Exception as error:
            detail = str(error).strip() or "erro desconhecido"
            yield f"[error] Erro de execução: {detail}\n"
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
