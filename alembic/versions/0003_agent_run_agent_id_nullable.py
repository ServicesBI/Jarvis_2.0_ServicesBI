"""agent_runs.agent_id nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-07

Contexto (Módulo 5A1 — AgentRun Schema / Repository Contract):

`AgentRun` representa uma TENTATIVA DE EXECUÇÃO DE UMA TASK, não
obrigatoriamente a execução de uma persona/agente registrada no
`AgentRegistry`. O chat comum/AUTO (a maioria das Tasks reais hoje —
confirmado na auditoria do Módulo 5A: 100% das 1.347 Tasks existentes em
`system/task-state.json` têm `agent_id=None`) nunca tem um `agent_id` de
persona associado; só chamadas via `POST /api/agents/{id}/run` têm.
`agent_runs.agent_id` era `NOT NULL`, o que tornava impossível registrar
uma tentativa de provider para esse caso majoritário sem inventar um
`agent_id` falso. Esta migration remove essa restrição.

Nenhuma outra coluna, índice, FK, UNIQUE constraint ou enum é alterado:
- `UNIQUE(task_id, attempt_number)` — inalterada.
- `UNIQUE(execution_key)` — inalterada.
- `ix_agent_runs_agent_id_status` — inalterada (índice composto continua
  válido com `agent_id IS NULL`; PostgreSQL simplesmente agrupa os NULLs).
- `attempt_number`, `execution_key`, `status` continuam `NOT NULL`.

RISCO CONHECIDO NO DOWNGRADE (documentado, não resolvido aqui):
`downgrade()` restaura `NOT NULL`. Isso falha (`IntegrityError` /
`NotNullViolation` do PostgreSQL) se já existir qualquer linha em
`agent_runs` com `agent_id IS NULL` no momento do downgrade — cenário
esperado assim que o 3A começar a criar AgentRuns para chat comum/AUTO.
Este bloco (5A1) NÃO inventa um backfill/valor-sentinela para viabilizar
o downgrade nesse cenário — isso ficaria fora do escopo aprovado. Um
downgrade só é seguro hoje enquanto nenhuma linha com `agent_id=NULL`
tiver sido gravada (ex.: banco de teste recém-migrado, ainda vazio).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "agent_runs",
        "agent_id",
        existing_type=sa.String(length=60),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema.

    Só é seguro se NENHUMA linha em `agent_runs` tiver `agent_id IS NULL`
    no momento da execução — ver docstring do módulo. Nenhum backfill é
    aplicado aqui; se houver linhas NULL, o PostgreSQL rejeita esta
    operação com um erro de NOT NULL violation, o que é o comportamento
    correto (falhar alto, não inventar dado).
    """
    op.alter_column(
        "agent_runs",
        "agent_id",
        existing_type=sa.String(length=60),
        nullable=False,
    )
