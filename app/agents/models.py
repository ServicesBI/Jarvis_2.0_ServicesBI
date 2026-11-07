"""Contratos imutáveis do catálogo de agentes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


_AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    id: str
    name: str
    role: str
    description: str
    status: AgentStatus
    canonical_persona: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _AGENT_ID_PATTERN.fullmatch(self.id):
            raise ValueError("Invalid agent id")
        for field_name in ("name", "role", "description", "canonical_persona"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid {field_name}")
        if not isinstance(self.status, AgentStatus):
            raise TypeError("status must be AgentStatus")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "status": self.status.value,
            "canonical_persona": self.canonical_persona,
        }
