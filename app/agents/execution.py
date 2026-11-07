"""Orquestra a execução real de um agente reaproveitando o ChatService existente."""

from __future__ import annotations

from typing import Any

from app.agents.registry import AgentRegistry
from app.agents.runtime import get_operating_profile
from app.agents.models import AgentStatus
from app.agents.state import AgentRuntimeStateService
from app.chat.models import ChatRequest
from app.chat.service import ChatService


async def _never_disconnected() -> bool:
    return False


class AgentExecutionService:
    """Entrypoint explícito para executar um agente com contrato operacional.

    Não cria Task diretamente: a task "chat.provider" já é criada pelo
    AvailabilityObservedExecutor (app/chat/executor.py) a partir de
    ChatRequest.agent_id, evitando um segundo lifecycle paralelo.
    """

    def __init__(
        self,
        chat_service: ChatService,
        agent_registry: AgentRegistry,
        state_service: AgentRuntimeStateService,
    ) -> None:
        self._chat_service = chat_service
        self._agent_registry = agent_registry
        self._state = state_service

    async def run(self, agent_id: str, message: str) -> dict[str, Any]:
        self._agent_registry.get(agent_id)
        profile = get_operating_profile(agent_id)
        return await self.run_with_prompt(agent_id, profile.operating_prompt, message)

    async def run_with_prompt(
        self, agent_id: str, operating_prompt: str, message: str
    ) -> dict[str, Any]:
        """Executa agent_id com uma instrução operacional explícita.

        Usado por run() para os 7 especialistas (via operating profile do
        registry) e diretamente por MorpheusOrchestrationService, cujo
        prompt não vive em _OPERATING_PROFILES (MORPHEUS não é executável
        via POST /api/agents/{id}/run).
        """

        self._agent_registry.get(agent_id)
        self._state.set_status(agent_id, AgentStatus.WORKING)
        request = ChatRequest(
            message=f"{operating_prompt}\n\n{message}",
            agent_id=agent_id,
        )
        chunks = [
            chunk
            async for chunk in self._chat_service.stream(request, _never_disconnected)
        ]
        content = "".join(chunks)

        if not content.strip() or content.startswith("[error]"):
            self._state.set_status(agent_id, AgentStatus.ERROR)
            return {"agent_id": agent_id, "status": "error", "output": content}

        self._state.set_status(agent_id, AgentStatus.IDLE)
        return {"agent_id": agent_id, "status": "completed", "output": content}
