"""add status check constraints

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

`TaskStatus`/`AgentRunStatus` são mapeados com `native_enum=False` (VARCHAR),
o que por padrão no SQLAlchemy 2.x NÃO gera um CHECK constraint automático.
Esta migration adiciona esse CHECK explicitamente, para que o PostgreSQL —
não só a camada Python/ORM — rejeite qualquer status fora do enum aprovado.
`timeout` continua fora de ambos os enums, por decisão já aprovada.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_STATUSES = ("pending", "running", "waiting_approval", "completed", "failed", "cancelled")
AGENT_RUN_STATUSES = ("pending", "running", "completed", "failed", "cancelled")


def upgrade() -> None:
    """Upgrade schema."""
    task_values = ", ".join(f"'{value}'" for value in TASK_STATUSES)
    op.create_check_constraint(
        "ck_tasks_status_valid",
        "tasks",
        f"status IN ({task_values})",
    )
    agent_run_values = ", ".join(f"'{value}'" for value in AGENT_RUN_STATUSES)
    op.create_check_constraint(
        "ck_agent_runs_status_valid",
        "agent_runs",
        f"status IN ({agent_run_values})",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_agent_runs_status_valid", "agent_runs", type_="check")
    op.drop_constraint("ck_tasks_status_valid", "tasks", type_="check")
