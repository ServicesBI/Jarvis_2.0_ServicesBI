"""Contratos de entrada e saída do Action Engine."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActionRisk(str, Enum):
    READ = "read"
    WRITE_FILE = "write_file"
    DESKTOP = "desktop"
    EXTERNAL = "external"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class PersistencePolicy(str, Enum):
    MINIMAL = "minimal"
    SANITIZED = "sanitized"


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=80)
    confirmed: bool = False

    @field_validator("action", "source")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class ActionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    exists: bool
    size: int | None = Field(default=None, ge=0)
    media_type: str | None = None


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    action: str
    summary: str | None = None
    artifacts: list[ActionArtifact] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
