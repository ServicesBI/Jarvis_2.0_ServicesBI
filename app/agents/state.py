"""Estado runtime dinâmico dos agentes, separado da definição canônica imutável."""

from __future__ import annotations

from threading import RLock

from app.agents.models import AgentStatus


class AgentRuntimeStateService:
    """Única fonte de status dinâmico. Não substitui o AgentRegistry."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._status: dict[str, AgentStatus] = {}

    def get_status(self, agent_id: str) -> AgentStatus:
        with self._lock:
            return self._status.get(agent_id, AgentStatus.IDLE)

    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        if not isinstance(status, AgentStatus):
            raise TypeError("status must be AgentStatus")
        with self._lock:
            self._status[agent_id] = status
