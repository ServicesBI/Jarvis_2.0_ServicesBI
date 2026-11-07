"""Modelos internos do serviço de chat."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRequest:
    """Entrada normalizada sem acoplar o serviço aos modelos do FastAPI."""

    message: str
    attachment_id: str | None = None
    from_voice: bool = False
    language: str = "BR"
    conclave_enabled: bool = True
    agent_id: str | None = None
