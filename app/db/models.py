"""Modelos SQLAlchemy do Jarvis — escopo desta fase: somente Task e AgentRun.

Decisões documentadas:
- Enums Python (`str, enum.Enum`) mapeados com `native_enum=False`: gera
  VARCHAR + CHECK constraint em vez de um tipo ENUM nativo do PostgreSQL.
  Um ENUM nativo exige `ALTER TYPE ... ADD VALUE` (fora de transação em
  versões mais antigas do PostgreSQL) para evoluir; VARCHAR+CHECK é trocado
  por uma migration comum, mais seguro para um schema ainda jovem.
- `id` usa o tipo UUID nativo do PostgreSQL. O `task_id` atual do TaskManager
  já é `uuid.uuid4().hex` (UUID válido, apenas sem hífens) — compatível.
- `timeout` não é um valor persistente de status (ver TaskStatus/AgentRunStatus);
  o mapeamento conceitual é `status=failed` + `failure_code="timeout"`.
- Nenhum chain-of-thought privado é armazenado; `output_text`/`summary`/
  `structured_result_json` guardam apenas o resultado relevante do agente.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    executor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(
            TaskStatus,
            name="task_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_json: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)

    agent_runs: Mapped[list["AgentRunRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_agent_id_status", "agent_id", "status"),
        Index("ix_tasks_created_at", "created_at"),
    )


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    execution_key: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(60), nullable=True)
    model_profile: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[AgentRunStatus] = mapped_column(
        SAEnum(
            AgentRunStatus,
            name="agent_run_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    input_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    context_json: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    operating_instructions_ref: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    output_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    structured_result_json: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    task: Mapped["TaskRecord"] = relationship(back_populates="agent_runs")

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_agent_runs_task_attempt"),
        UniqueConstraint("execution_key", name="uq_agent_runs_execution_key"),
        Index("ix_agent_runs_task_id", "task_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_agent_id_status", "agent_id", "status"),
        Index("ix_agent_runs_created_at", "created_at"),
    )
