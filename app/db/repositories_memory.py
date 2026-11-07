"""Implementações in-memory (fakes) de TaskRepository/AgentRunRepository.

Uso exclusivo em testes unitários. Não é uma segunda fonte de produção.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime

from app.db.models import AgentRunRecord, AgentRunStatus, TaskRecord, TaskStatus
from app.db.repositories import (
    DuplicateAttemptError,
    DuplicateExecutionKeyError,
    TaskNotFoundError,
)


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[uuid.UUID, TaskRecord] = {}
        self._lock = threading.Lock()

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
        with self._lock:
            task = TaskRecord(
                id=id if id is not None else uuid.uuid4(),
                type=type,
                status=status,
                description=description,
                executor=executor,
                display_name=display_name,
                agent_id=agent_id,
                created_at=created_at if created_at is not None else _utcnow(),
                started_at=started_at,
                finished_at=finished_at,
                result_json=result_json,
                error_text=error_text,
                failure_code=failure_code,
            )
            self._tasks[task.id] = task
            return task

    def get(self, task_id: uuid.UUID) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[TaskRecord]:
        with self._lock:
            tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        if agent_id is not None:
            tasks = [task for task in tasks if task.agent_id == agent_id]
        return tasks

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
    ) -> TaskRecord:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(f"Task {task_id} não encontrada.")
            task.status = status
            if started_at is not None:
                task.started_at = started_at
            if finished_at is not None:
                task.finished_at = finished_at
            if result_json is not None:
                task.result_json = result_json
            if error_text is not None:
                task.error_text = error_text
            if failure_code is not None:
                task.failure_code = failure_code
            return task


class InMemoryAgentRunRepository:
    def __init__(self, *, task_repository: InMemoryTaskRepository) -> None:
        self._task_repository = task_repository
        self._runs: dict[uuid.UUID, AgentRunRecord] = {}
        self._lock = threading.Lock()

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
    ) -> AgentRunRecord:
        with self._lock:
            if self._task_repository.get(task_id) is None:
                raise TaskNotFoundError(f"Task {task_id} não encontrada.")
            for run in self._runs.values():
                if run.task_id == task_id and run.attempt_number == attempt_number:
                    raise DuplicateAttemptError(
                        f"Attempt {attempt_number} já existe para a task {task_id}."
                    )
                if run.execution_key == execution_key:
                    raise DuplicateExecutionKeyError(
                        f"execution_key {execution_key!r} já está em uso."
                    )
            now = _utcnow()
            run = AgentRunRecord(
                id=uuid.uuid4(),
                task_id=task_id,
                attempt_number=attempt_number,
                execution_key=execution_key,
                agent_id=agent_id,
                status=status,
                provider=provider,
                model_profile=model_profile,
                input_text=input_text,
                context_json=context_json,
                operating_instructions_ref=operating_instructions_ref,
                created_at=now,
                updated_at=now,
            )
            self._runs[run.id] = run
            return run

    def get(self, run_id: uuid.UUID) -> AgentRunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_for_task(self, task_id: uuid.UUID) -> list[AgentRunRecord]:
        with self._lock:
            return [run for run in self._runs.values() if run.task_id == task_id]

    def get_by_execution_key(self, execution_key: str) -> AgentRunRecord | None:
        with self._lock:
            for run in self._runs.values():
                if run.execution_key == execution_key:
                    return run
            return None

    def next_attempt_number(self, task_id: uuid.UUID) -> int:
        with self._lock:
            attempts = [
                run.attempt_number
                for run in self._runs.values()
                if run.task_id == task_id
            ]
            return max(attempts, default=0) + 1

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
    ) -> AgentRunRecord:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise TaskNotFoundError(f"AgentRun {run_id} não encontrado.")
            run.status = status
            if started_at is not None:
                run.started_at = started_at
            if finished_at is not None:
                run.finished_at = finished_at
            if output_text is not None:
                run.output_text = output_text
            if structured_result_json is not None:
                run.structured_result_json = structured_result_json
            if summary is not None:
                run.summary = summary
            if error_text is not None:
                run.error_text = error_text
            if failure_code is not None:
                run.failure_code = failure_code
            run.updated_at = _utcnow()
            return run
