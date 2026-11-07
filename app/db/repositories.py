"""Contratos de repositório para Task/AgentRun.

Repository = persistência. Regras de negócio/lifecycle continuam no
TaskManager (futuro) — nada aqui decide *quando* uma Task deve transicionar,
apenas *como* o estado é lido/gravado.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from app.db.models import AgentRunRecord, AgentRunStatus, TaskRecord, TaskStatus


class TaskNotFoundError(LookupError):
    """A Task referenciada não existe."""


class DuplicateAttemptError(ValueError):
    """Já existe um AgentRun com o mesmo (task_id, attempt_number)."""


class DuplicateExecutionKeyError(ValueError):
    """Já existe um AgentRun com o mesmo execution_key."""


class TaskRepository(Protocol):
    def create(
        self,
        *,
        type: str,
        status: TaskStatus,
        description: str | None = None,
        executor: str | None = None,
        display_name: str | None = None,
        agent_id: str | None = None,
        id: uuid.UUID | None = None,
        created_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        result_json: dict | None = None,
        error_text: str | None = None,
        failure_code: str | None = None,
    ) -> TaskRecord:
        """`id`/`created_at`/... são only-for-migration: quando omitidos,
        continuam auto-gerados (id=uuid4, created_at=agora) exatamente como
        antes — usados explicitamente só por app.db.migrate_task_state, para
        preservar o task_id e os timestamps originais do JSON legado."""
        ...

    def get(self, task_id: uuid.UUID) -> TaskRecord | None: ...

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[TaskRecord]: ...

    def update_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        result_json: dict | None = None,
        error_text: str | None = None,
        failure_code: str | None = None,
    ) -> TaskRecord: ...


class AgentRunRepository(Protocol):
    def create(
        self,
        *,
        task_id: uuid.UUID,
        attempt_number: int,
        execution_key: str,
        agent_id: str | None,
        status: AgentRunStatus,
        provider: str | None = None,
        model_profile: str | None = None,
        input_text: str | None = None,
        context_json: dict | None = None,
        operating_instructions_ref: str | None = None,
    ) -> AgentRunRecord: ...

    def get(self, run_id: uuid.UUID) -> AgentRunRecord | None: ...

    def list_for_task(self, task_id: uuid.UUID) -> list[AgentRunRecord]: ...

    def get_by_execution_key(self, execution_key: str) -> AgentRunRecord | None: ...

    def next_attempt_number(self, task_id: uuid.UUID) -> int: ...

    def update_status(
        self,
        run_id: uuid.UUID,
        status: AgentRunStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        output_text: str | None = None,
        structured_result_json: dict | None = None,
        summary: str | None = None,
        error_text: str | None = None,
        failure_code: str | None = None,
    ) -> AgentRunRecord: ...
