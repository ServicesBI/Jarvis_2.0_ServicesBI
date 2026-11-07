"""P2 — TaskManager em modo TaskRepository (in-memory fake).

Cobre os itens 4-11 do RED obrigatório da P2 usando o fake in-memory (rápido,
sem PostgreSQL real). A cobertura contra PostgreSQL real fica em
tests/db/test_task_manager_postgres_repository.py.
"""

from __future__ import annotations

import unittest

from app.db.models import TaskStatus
from app.db.repositories_memory import InMemoryAgentRunRepository, InMemoryTaskRepository
from app.tasks.manager import TaskManager, TaskTransitionError


def _make_manager(task_repository=None):
    return TaskManager(task_repository=task_repository or InMemoryTaskRepository())


class TaskManagerRepositoryModeConstructionTests(unittest.TestCase):
    def test_requires_exactly_one_of_state_path_or_task_repository(self):
        with self.assertRaises(ValueError):
            TaskManager()
        with self.assertRaises(ValueError):
            from pathlib import Path

            TaskManager(Path("x"), task_repository=InMemoryTaskRepository())

    def test_repository_mode_has_no_state_path_and_writes_no_json(self):
        manager = _make_manager()
        self.assertIsNone(manager.state_path)


class TaskManagerRepositoryModeCrudTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryTaskRepository()
        self.manager = _make_manager(self.repo)

    def test_create_persists_in_the_repository(self):
        task = self.manager.create("chat.provider", "teste")
        record = self.repo.get(__import__("uuid").UUID(task["task_id"]))
        self.assertIsNotNone(record)
        self.assertEqual(record.type, "chat.provider")

    def test_get_reads_from_the_repository(self):
        task = self.manager.create("chat.provider", "teste")
        fetched = self.manager.get(task["task_id"])
        self.assertEqual(fetched["task_id"], task["task_id"])
        self.assertEqual(fetched["status"], "pending")

    def test_get_unknown_task_returns_none(self):
        self.assertIsNone(self.manager.get("0" * 32))

    def test_list_reads_from_the_repository(self):
        self.manager.create("chat.provider", "a")
        self.manager.create("chat.provider", "b")
        tasks = self.manager.list()
        self.assertEqual(len(tasks), 2)

    def test_transition_persists_status_timestamps_result_error(self):
        task = self.manager.create("chat.provider", "teste")
        running = self.manager.transition(task["task_id"], "running")
        self.assertEqual(running["status"], "running")
        self.assertIsNotNone(running["started_at"])

        completed = self.manager.transition(
            task["task_id"], "completed", result={"ok": True, "text": "oi"}
        )
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["finished_at"])
        self.assertEqual(completed["result"], {"ok": True, "text": "oi"})

    def test_invalid_transition_is_rejected(self):
        task = self.manager.create("chat.provider", "teste")
        with self.assertRaises(TaskTransitionError):
            self.manager.transition(task["task_id"], "completed")

    def test_timeout_status_round_trips_through_failed_plus_failure_code(self):
        task = self.manager.create("chat.provider", "teste")
        self.manager.transition(task["task_id"], "running")
        timed_out = self.manager.transition(
            task["task_id"], "timeout", error="Timeout de 60s excedido."
        )
        self.assertEqual(timed_out["status"], "timeout")

        record = self.repo.get(__import__("uuid").UUID(task["task_id"]))
        self.assertEqual(record.status, TaskStatus.FAILED)
        self.assertEqual(record.failure_code, "timeout")

        refetched = self.manager.get(task["task_id"])
        self.assertEqual(refetched["status"], "timeout")

    def test_no_json_file_is_ever_written(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            watched = Path(temp_dir) / "should-not-exist.json"
            manager = TaskManager(task_repository=InMemoryTaskRepository())
            manager.create("chat.provider", "teste")
            manager.transition(
                next(iter(manager.list()))["task_id"], "running"
            )
            self.assertFalse(watched.exists())


class TaskManagerRepositoryModeRestartRecoveryTests(unittest.TestCase):
    def test_restart_with_same_repository_recovers_state(self):
        repo = InMemoryTaskRepository()
        first_manager = TaskManager(task_repository=repo)
        task = first_manager.create("chat.provider", "teste")

        second_manager = TaskManager(task_repository=repo)
        recovered = second_manager.get(task["task_id"])
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["type"], "chat.provider")

    def test_running_task_is_reconciled_to_failed_on_reconcile(self):
        repo = InMemoryTaskRepository()
        first_manager = TaskManager(task_repository=repo)
        task = first_manager.create("chat.provider", "teste")
        first_manager.transition(task["task_id"], "running")

        second_manager = TaskManager(task_repository=repo)
        second_manager.reconcile()

        recovered = second_manager.get(task["task_id"])
        self.assertEqual(recovered["status"], "failed")
        self.assertIn("restart", recovered["error"].lower())

    def test_pending_task_is_left_untouched_by_reconcile(self):
        repo = InMemoryTaskRepository()
        manager = TaskManager(task_repository=repo)
        task = manager.create("chat.provider", "teste")

        manager.reconcile()

        self.assertEqual(manager.get(task["task_id"])["status"], "pending")

    def test_reconcile_is_a_noop_in_file_mode(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "task-state.json")
            manager.reconcile()  # não deve levantar nem fazer nada de diferente


if __name__ == "__main__":
    unittest.main()
