"""Contrato de executor usado pelo serviço de chat."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Callable, Mapping

from app.chat.models import ChatRequest
from app.executors.availability import ProviderAvailabilityService
from app.providers.manager import ProviderManager
from app.tasks.manager import TaskManager, TaskTransitionError


class ChatExecutor(ABC):
    """Interface preparada para um futuro Executor Manager."""

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """Produz texto incremental já compatível com os marcadores do frontend."""

    async def on_client_disconnect(self, request: ChatRequest) -> None:
        """Notifica desconexão sem impor que o executor mate seu processo."""


class UnavailableChatExecutor(ChatExecutor):
    """Fallback seguro usado enquanto nenhum provedor real foi migrado."""

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        messages = {
            "BR": "[error] Sistema de execução não configurado.\n",
            "ES": "[error] Sistema de ejecución no configurado.\n",
            "EN": "[error] Execution system is not configured.\n",
        }
        yield messages.get(request.language, messages["EN"])


class NoEligibleProviderExecutor(ChatExecutor):
    """Erro seguro quando o modo auto não possui candidato operacional."""

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        messages = {
            "BR": "[error] Nenhum provedor elegível está disponível no momento.\n",
            "ES": "[error] No hay ningún proveedor elegible disponible.\n",
            "EN": "[error] No eligible provider is currently available.\n",
        }
        yield messages.get(request.language, messages["EN"])


class AvailabilityObservedExecutor(ChatExecutor):
    """Atualiza capacidade real após uma execução manual ou automática."""

    def __init__(
        self,
        provider: str,
        executor: ChatExecutor,
        availability: ProviderAvailabilityService,
        provider_manager: ProviderManager | None = None,
        task_manager: TaskManager | None = None,
    ) -> None:
        self.provider = provider
        self.executor = executor
        self.availability = availability
        self.provider_manager = provider_manager
        self.task_manager = task_manager

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        produced_output = False
        task = (
            self.task_manager.create(
                "chat.provider",
                "Solicitacao de chat",
                executor=self.provider,
                display_name="Solicitacao de chat",
                agent_id=request.agent_id,
            )
            if self.task_manager
            else None
        )
        if task:
            self.task_manager.transition(task["task_id"], "running")
        try:
            async for chunk in self.executor.stream(request):
                if chunk:
                    produced_output = True
                    yield chunk
        except asyncio.CancelledError:
            if task:
                self.task_manager._try_terminal_transition(task["task_id"], "cancelled")
            raise
        except Exception as error:
            self.availability.record_failure(self.provider, error)
            if self.provider_manager is not None:
                self.provider_manager.record_failure(self.provider, error)
            if task:
                self.task_manager._try_terminal_transition(task["task_id"], "failed", error=type(error).__name__)
            raise

        if produced_output:
            self.availability.record_success(self.provider)
            if self.provider_manager is not None:
                self.provider_manager.record_success(self.provider)
            if task:
                self.task_manager._try_terminal_transition(task["task_id"], "completed", result={"ok": True})
        else:
            error = RuntimeError("executor não retornou saída")
            self.availability.record_failure(self.provider, error)
            if self.provider_manager is not None:
                self.provider_manager.record_failure(self.provider, error)
            if task:
                self.task_manager._try_terminal_transition(task["task_id"], "failed", error="no_output")
            raise error

    async def on_client_disconnect(self, request: ChatRequest) -> None:
        await self.executor.on_client_disconnect(request)


class AutoChatExecutor(ChatExecutor):
    """Seleciona o primeiro executor elegível e tenta o próximo em falha."""

    def __init__(
        self,
        executors: Mapping[str, ChatExecutor],
        availability: ProviderAvailabilityService,
        unavailable: ChatExecutor,
        model_available: Callable[[str], bool] | None = None,
    ) -> None:
        self.executors = dict(executors)
        self.availability = availability
        self.unavailable = unavailable
        self.model_available = model_available or (lambda provider: True)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        await self.availability.refresh()
        candidates = self.availability.eligible_providers(self.executors)

        for provider in candidates:
            if not self.model_available(provider):
                continue
            emitted = False
            try:
                async for chunk in self.executors[provider].stream(request):
                    emitted = True
                    yield chunk
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if emitted:
                    raise
                continue

        async for chunk in self.unavailable.stream(request):
            yield chunk


class ModeAwareChatExecutor(ChatExecutor):
    """Seleciona um adaptador manual ou o orquestrador do modo auto."""

    def __init__(
        self,
        mode_provider: Callable[[], str],
        executors: Mapping[str, ChatExecutor],
        unavailable: ChatExecutor,
        availability: ProviderAvailabilityService | None = None,
    ) -> None:
        self._mode_provider = mode_provider
        self._executors = dict(executors)
        self._unavailable = unavailable
        self._availability = availability

    def _selected(self) -> ChatExecutor:
        return self._executors.get(self._mode_provider(), self._unavailable)

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        provider = self._mode_provider()
        if self._availability is not None and provider != "auto":
            await self._availability.refresh()
            if provider in self._executors and not self._availability.can_attempt(
                provider, automatic=False
            ):
                async for chunk in self._unavailable.stream(request):
                    yield chunk
                return
        async for chunk in self._selected().stream(request):
            yield chunk

    async def on_client_disconnect(self, request: ChatRequest) -> None:
        await self._selected().on_client_disconnect(request)
