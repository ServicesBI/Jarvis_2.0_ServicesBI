"""P1 — repositórios PostgreSQL reais (integração).

Estes testes só rodam contra um banco de TESTE explicitamente marcado via
JARVIS_TEST_DATABASE_URL. Nunca usam JARVIS_DATABASE_URL de produção.

Sem essa variável (o caso hoje neste ambiente, confirmado pela auditoria),
a suíte inteira faz SKIP explícito — não falha silenciosamente, não finge
sucesso, não cai para SQLite.
"""

from __future__ import annotations

import unittest
import uuid

from app.core.config import get_setting

TEST_DATABASE_URL = get_setting("JARVIS_TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "JARVIS_TEST_DATABASE_URL não configurada — integração PostgreSQL real "
    "requer provisionamento manual de um banco de teste isolado (passo humano, "
    "fora do escopo desta tarefa).",
)
class PostgresRepositoryIntegrationTests(unittest.TestCase):
    """Fixture nunca dropa schema — só aplica migrations (idempotente) e
    trunca as linhas. Isso garante que rodar a suíte 2x seguidas funciona sem
    ressincronização manual: alembic_version nunca fica dessincronizado do
    estado real das tabelas (ver Precondição B da P2)."""

    @classmethod
    def setUpClass(cls) -> None:
        from app.db.engine import create_database_engine, create_session_factory
        from app.db.migration_runner import upgrade_to_head

        upgrade_to_head(TEST_DATABASE_URL)
        cls.engine = create_database_engine(TEST_DATABASE_URL)
        cls.session_factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        from sqlalchemy import text

        from app.db.repositories_postgres import (
            PostgresAgentRunRepository,
            PostgresTaskRepository,
        )

        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE agent_runs, tasks"))

        self.task_repo = PostgresTaskRepository(session_factory=self.session_factory)
        self.run_repo = PostgresAgentRunRepository(session_factory=self.session_factory)

    def test_migration_creates_only_tasks_and_agent_runs(self) -> None:
        # `alembic_version` é a tabela de controle do próprio Alembic — legítima,
        # não é uma entidade de negócio. Nenhuma outra tabela pode existir.
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        self.assertTrue({"tasks", "agent_runs"}.issubset(tables))
        self.assertTrue(tables.issubset({"tasks", "agent_runs", "alembic_version"}))

    def test_create_and_get_task(self) -> None:
        from app.db.models import TaskStatus

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        fetched = self.task_repo.get(task.id)
        self.assertEqual(fetched.id, task.id)

    def test_create_and_get_agent_run(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        run = self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        fetched = self.run_repo.get(run.id)
        self.assertEqual(fetched.id, run.id)

    def test_foreign_key_is_enforced(self) -> None:
        from app.db.models import AgentRunStatus
        from app.db.repositories import TaskNotFoundError

        with self.assertRaises(TaskNotFoundError):
            self.run_repo.create(
                task_id=uuid.uuid4(),
                attempt_number=1,
                execution_key=f"key-{uuid.uuid4()}",
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_unique_attempt_is_enforced(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus
        from app.db.repositories import DuplicateAttemptError

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateAttemptError):
            self.run_repo.create(
                task_id=task.id,
                attempt_number=1,
                execution_key=f"key-{uuid.uuid4()}",
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_unique_execution_key_is_enforced(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus
        from app.db.repositories import DuplicateExecutionKeyError

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        shared_key = f"key-{uuid.uuid4()}"
        self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=shared_key,
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateExecutionKeyError):
            self.run_repo.create(
                task_id=task.id,
                attempt_number=2,
                execution_key=shared_key,
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_create_agent_run_without_agent_id(self) -> None:
        """Módulo 5A1: chat comum/AUTO cria AgentRun com agent_id=NULL no
        PostgreSQL real — prova que o NOT NULL foi removido no banco, não só
        na camada ORM."""
        from app.db.models import AgentRunStatus, TaskStatus

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        run = self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id=None,
            provider="codex",
            status=AgentRunStatus.PENDING,
        )
        fetched = self.run_repo.get(run.id)
        self.assertIsNone(fetched.agent_id)
        self.assertEqual(fetched.provider, "codex")

    def test_agent_id_filled_still_works(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        run = self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        fetched = self.run_repo.get(run.id)
        self.assertEqual(fetched.agent_id, "neo")

    def test_unique_attempt_is_enforced_even_with_agent_id_none(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus
        from app.db.repositories import DuplicateAttemptError

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id=None,
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateAttemptError):
            self.run_repo.create(
                task_id=task.id,
                attempt_number=1,
                execution_key=f"key-{uuid.uuid4()}",
                agent_id=None,
                status=AgentRunStatus.PENDING,
            )

    def test_next_attempt_number_starts_at_one_and_increments(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus

        task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        self.assertEqual(self.run_repo.next_attempt_number(task.id), 1)
        self.run_repo.create(
            task_id=task.id,
            attempt_number=1,
            execution_key=f"key-{uuid.uuid4()}",
            agent_id=None,
            status=AgentRunStatus.PENDING,
        )
        self.assertEqual(self.run_repo.next_attempt_number(task.id), 2)

    def test_transactional_rollback_leaves_no_partial_state(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus
        from app.db.repositories_postgres import (
            PostgresAgentRunRepository,
            PostgresTaskRepository,
        )
        from app.db.uow import unit_of_work

        shared_key = f"key-{uuid.uuid4()}"
        task_id_holder: list[uuid.UUID] = []
        try:
            with unit_of_work(self.session_factory) as session:
                scoped_task_repo = PostgresTaskRepository(session=session)
                scoped_run_repo = PostgresAgentRunRepository(session=session)
                task = scoped_task_repo.create(
                    type="chat.provider", status=TaskStatus.PENDING
                )
                task_id_holder.append(task.id)
                scoped_run_repo.create(
                    task_id=task.id,
                    attempt_number=1,
                    execution_key=shared_key,
                    agent_id="neo",
                    status=AgentRunStatus.PENDING,
                )
                scoped_run_repo.create(
                    task_id=task.id,
                    attempt_number=2,
                    execution_key=shared_key,
                    agent_id="neo",
                    status=AgentRunStatus.PENDING,
                )
        except Exception:
            pass
        else:
            self.fail("esperava falha de execution_key duplicado dentro da transação")

        self.assertIsNone(self.task_repo.get(task_id_holder[0]))


if __name__ == "__main__":
    unittest.main()
