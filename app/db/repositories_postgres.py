"""Implementações PostgreSQL (SQLAlchemy) de TaskRepository/AgentRunRepository.

Cada repository aceita OU um `session_factory` (modo independente: abre,
comita e fecha sua própria Session a cada chamada) OU uma `session` explícita
(modo participante: entra numa transação já aberta por `app.db.uow.unit_of_work`
e não comita/fecha nada — quem controla o commit/rollback é o chamador).

`next_attempt_number` + `create` só se tornam uma operação verdadeiramente
serializada contra escritas concorrentes quando chamados dentro da MESMA
Session/transação (modo participante) — o lock `SELECT ... FOR UPDATE` na
Task pai é liberado no commit dessa transação.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AgentRunRecord, AgentRunStatus, TaskRecord, TaskStatus
from app.db.repositories import (
    DuplicateAttemptError,
    DuplicateExecutionKeyError,
    TaskNotFoundError,
)


class _SessionScopedRepository:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        session: Session | None = None,
    ) -> None:
        if (session_factory is None) == (session is None):
            raise ValueError(
                "Informe exatamente um de session_factory ou session."
            )
        self._session_factory = session_factory
        self._external_session = session

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        if self._external_session is not None:
            yield self._external_session
            return
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class PostgresTaskRepository(_SessionScopedRepository):
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
        with self._session_scope() as session:
            task = TaskRecord(
                id=id if id is not None else uuid.uuid4(),
                type=type,
                status=status,
                description=description,
                executor=executor,
                display_name=display_name,
                agent_id=agent_id,
                started_at=started_at,
                finished_at=finished_at,
                result_json=result_json,
                error_text=error_text,
                failure_code=failure_code,
            )
            if created_at is not None:
                task.created_at = created_at
            session.add(task)
            session.flush()
            return task

    def get(self, task_id: uuid.UUID) -> TaskRecord | None:
        with self._session_scope() as session:
            return session.get(TaskRecord, task_id)

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        agent_id: str | None = None,
    ) -> list[TaskRecord]:
        with self._session_scope() as session:
            statement = select(TaskRecord)
            if status is not None:
                statement = statement.where(TaskRecord.status == status)
            if agent_id is not None:
                statement = statement.where(TaskRecord.agent_id == agent_id)
            return list(session.execute(statement).scalars())

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
        with self._session_scope() as session:
            task = session.get(TaskRecord, task_id)
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
            session.flush()
            return task


class PostgresAgentRunRepository(_SessionScopedRepository):
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
        with self._session_scope() as session:
            if session.get(TaskRecord, task_id) is None:
                raise TaskNotFoundError(f"Task {task_id} não encontrada.")
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
            )
            session.add(run)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                message = str(exc.orig)
                if "uq_agent_runs_task_attempt" in message:
                    raise DuplicateAttemptError(
                        f"Attempt {attempt_number} já existe para a task {task_id}."
                    ) from exc
                if "uq_agent_runs_execution_key" in message:
                    raise DuplicateExecutionKeyError(
                        f"execution_key {execution_key!r} já está em uso."
                    ) from exc
                raise
            return run

    def get(self, run_id: uuid.UUID) -> AgentRunRecord | None:
        with self._session_scope() as session:
            return session.get(AgentRunRecord, run_id)

    def list_for_task(self, task_id: uuid.UUID) -> list[AgentRunRecord]:
        with self._session_scope() as session:
            statement = select(AgentRunRecord).where(
                AgentRunRecord.task_id == task_id
            )
            return list(session.execute(statement).scalars())

    def get_by_execution_key(self, execution_key: str) -> AgentRunRecord | None:
        with self._session_scope() as session:
            statement = select(AgentRunRecord).where(
                AgentRunRecord.execution_key == execution_key
            )
            return session.execute(statement).scalar_one_or_none()

    def next_attempt_number(self, task_id: uuid.UUID) -> int:
        with self._session_scope() as session:
            task = session.execute(
                select(TaskRecord).where(TaskRecord.id == task_id).with_for_update()
            ).scalar_one_or_none()
            if task is None:
                raise TaskNotFoundError(f"Task {task_id} não encontrada.")
            max_attempt = session.execute(
                select(func.max(AgentRunRecord.attempt_number)).where(
                    AgentRunRecord.task_id == task_id
                )
            ).scalar()
            return (max_attempt or 0) + 1

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
        with self._session_scope() as session:
            run = session.get(AgentRunRecord, run_id)
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
            session.flush()
            return run
