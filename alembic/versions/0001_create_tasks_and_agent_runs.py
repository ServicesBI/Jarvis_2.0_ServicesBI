"""create tasks and agent_runs

Revision ID: 0001
Revises:
Create Date: 2026-09-04

Escopo desta migration: SOMENTE as tabelas `tasks` e `agent_runs` (P0/P1).
Nenhuma outra entidade aprovada (projects, milestones, orchestration_sessions,
orchestration_steps, approvals, decisions, audit_events) é criada aqui.

Escrita manualmente (não via --autogenerate) porque nenhum banco de destino
está configurado nesta fase — não há conexão real contra a qual comparar.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("type", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("executor", sa.String(length=120), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("agent_id", sa.String(length=60), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "waiting_approval",
                "completed",
                "failed",
                "cancelled",
                name="task_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_agent_id_status", "tasks", ["agent_id", "status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])

    op.create_table(
        "agent_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("execution_key", sa.String(length=200), nullable=False),
        sa.Column("agent_id", sa.String(length=60), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=True),
        sa.Column("model_profile", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="agent_run_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("operating_instructions_ref", sa.String(length=200), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("structured_result_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "task_id", "attempt_number", name="uq_agent_runs_task_attempt"
        ),
        sa.UniqueConstraint("execution_key", name="uq_agent_runs_execution_key"),
    )
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index(
        "ix_agent_runs_agent_id_status", "agent_runs", ["agent_id", "status"]
    )
    op.create_index("ix_agent_runs_created_at", "agent_runs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_runs_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_id_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_task_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_tasks_agent_id_status", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")
