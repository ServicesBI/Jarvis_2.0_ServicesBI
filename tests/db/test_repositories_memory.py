"""P1 — repositórios in-memory (fakes) para Task/AgentRun.

Cobre os itens 12-20 do brief aprovado. Nenhum banco real é usado — as
regras de unicidade/FK são impostas em Python pelos próprios fakes, do
mesmo jeito que seriam impostas por constraints reais no PostgreSQL.
"""

from __future__ import annotations

import unittest


class InMemoryTaskRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.db.repositories_memory import InMemoryTaskRepository

        self.repo = InMemoryTaskRepository()

    def test_create_and_get(self) -> None:
        from app.db.models import TaskStatus

        task = self.repo.create(type="chat.provider", status=TaskStatus.PENDING)
        fetched = self.repo.get(task.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, task.id)
        self.assertEqual(fetched.type, "chat.provider")
        self.assertEqual(fetched.status, TaskStatus.PENDING)

    def test_get_unknown_task_returns_none(self) -> None:
        import uuid

        self.assertIsNone(self.repo.get(uuid.uuid4()))

    def test_list_returns_all_created_tasks(self) -> None:
        from app.db.models import TaskStatus

        self.repo.create(type="chat.provider", status=TaskStatus.PENDING)
        self.repo.create(type="excel.create", status=TaskStatus.PENDING)
        tasks = self.repo.list()
        self.assertEqual(len(tasks), 2)

    def test_list_can_filter_by_status(self) -> None:
        from app.db.models import TaskStatus

        self.repo.create(type="chat.provider", status=TaskStatus.PENDING)
        running = self.repo.create(type="chat.provider", status=TaskStatus.RUNNING)
        result = self.repo.list(status=TaskStatus.RUNNING)
        self.assertEqual([task.id for task in result], [running.id])

    def test_update_status_persists_the_new_status(self) -> None:
        from app.db.models import TaskStatus

        task = self.repo.create(type="chat.provider", status=TaskStatus.PENDING)
        updated = self.repo.update_status(task.id, TaskStatus.RUNNING)
        self.assertEqual(updated.status, TaskStatus.RUNNING)
        self.assertEqual(self.repo.get(task.id).status, TaskStatus.RUNNING)

    def test_update_status_of_unknown_task_raises(self) -> None:
        import uuid

        from app.db.models import TaskStatus
        from app.db.repositories import TaskNotFoundError

        with self.assertRaises(TaskNotFoundError):
            self.repo.update_status(uuid.uuid4(), TaskStatus.RUNNING)


class InMemoryAgentRunRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.db.models import TaskStatus
        from app.db.repositories_memory import (
            InMemoryAgentRunRepository,
            InMemoryTaskRepository,
        )

        self.task_repo = InMemoryTaskRepository()
        self.run_repo = InMemoryAgentRunRepository(task_repository=self.task_repo)
        self.task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)

    def test_create_and_get(self) -> None:
        from app.db.models import AgentRunStatus

        run = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-1",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        fetched = self.run_repo.get(run.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.agent_id, "neo")

    def test_list_for_task_returns_only_that_tasks_runs(self) -> None:
        from app.db.models import AgentRunStatus, TaskStatus

        other_task = self.task_repo.create(type="chat.provider", status=TaskStatus.PENDING)
        run_a = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-a",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        self.run_repo.create(
            task_id=other_task.id,
            attempt_number=1,
            execution_key="key-b",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        runs = self.run_repo.list_for_task(self.task.id)
        self.assertEqual([run.id for run in runs], [run_a.id])

    def test_two_attempts_of_the_same_task_coexist(self) -> None:
        from app.db.models import AgentRunStatus

        first = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-1",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        second = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=2,
            execution_key="key-2",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        runs = self.run_repo.list_for_task(self.task.id)
        self.assertEqual({run.id for run in runs}, {first.id, second.id})

    def test_duplicate_attempt_number_is_rejected(self) -> None:
        from app.db.models import AgentRunStatus
        from app.db.repositories import DuplicateAttemptError

        self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-1",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateAttemptError):
            self.run_repo.create(
                task_id=self.task.id,
                attempt_number=1,
                execution_key="key-2",
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_duplicate_execution_key_is_rejected(self) -> None:
        from app.db.models import AgentRunStatus
        from app.db.repositories import DuplicateExecutionKeyError

        self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="same-key",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateExecutionKeyError):
            self.run_repo.create(
                task_id=self.task.id,
                attempt_number=2,
                execution_key="same-key",
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_run_for_unknown_task_is_rejected(self) -> None:
        import uuid

        from app.db.models import AgentRunStatus
        from app.db.repositories import TaskNotFoundError

        with self.assertRaises(TaskNotFoundError):
            self.run_repo.create(
                task_id=uuid.uuid4(),
                attempt_number=1,
                execution_key="key-x",
                agent_id="neo",
                status=AgentRunStatus.PENDING,
            )

    def test_get_by_execution_key(self) -> None:
        from app.db.models import AgentRunStatus

        run = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="lookup-key",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        found = self.run_repo.get_by_execution_key("lookup-key")
        self.assertEqual(found.id, run.id)
        self.assertIsNone(self.run_repo.get_by_execution_key("missing"))

    def test_next_attempt_number_starts_at_one_and_increments(self) -> None:
        from app.db.models import AgentRunStatus

        self.assertEqual(self.run_repo.next_attempt_number(self.task.id), 1)
        self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-1",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        self.assertEqual(self.run_repo.next_attempt_number(self.task.id), 2)

    def test_update_status_persists_output_fields(self) -> None:
        from app.db.models import AgentRunStatus

        run = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-1",
            agent_id="neo",
            status=AgentRunStatus.PENDING,
        )
        updated = self.run_repo.update_status(
            run.id, AgentRunStatus.COMPLETED, output_text="resposta completa"
        )
        self.assertEqual(updated.status, AgentRunStatus.COMPLETED)
        self.assertEqual(updated.output_text, "resposta completa")

    def test_create_with_agent_id_none_is_accepted(self) -> None:
        """Módulo 5A1: chat comum/AUTO não tem persona associada — o valor
        NULL precisa ser um estado válido, não um erro de validação."""
        from app.db.models import AgentRunStatus

        run = self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-no-agent",
            agent_id=None,
            provider="codex",
            status=AgentRunStatus.PENDING,
        )
        fetched = self.run_repo.get(run.id)
        self.assertIsNone(fetched.agent_id)
        self.assertEqual(fetched.provider, "codex")

    def test_duplicate_attempt_number_is_rejected_even_with_agent_id_none(self) -> None:
        """UNIQUE(task_id, attempt_number) não pode depender de agent_id ser
        preenchido — precisa continuar protegida quando agent_id=None."""
        from app.db.models import AgentRunStatus
        from app.db.repositories import DuplicateAttemptError

        self.run_repo.create(
            task_id=self.task.id,
            attempt_number=1,
            execution_key="key-none-1",
            agent_id=None,
            status=AgentRunStatus.PENDING,
        )
        with self.assertRaises(DuplicateAttemptError):
            self.run_repo.create(
                task_id=self.task.id,
                attempt_number=1,
                execution_key="key-none-2",
                agent_id=None,
                status=AgentRunStatus.PENDING,
            )


if __name__ == "__main__":
    unittest.main()
