"""P2 — TaskManager em modo repository contra PostgreSQL real (jarvis_test).

Mesma cobertura essencial de tests/test_task_manager_repository_mode.py, mas
provando que a abstração funciona de fato contra o banco real, não só o fake.
"""

from __future__ import annotations

import unittest

from app.core.config import get_setting

TEST_DATABASE_URL = get_setting("JARVIS_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "JARVIS_TEST_DATABASE_URL não configurada.")
class TaskManagerPostgresRepositoryTests(unittest.TestCase):
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

        from app.db.repositories_postgres import PostgresTaskRepository
        from app.tasks.manager import TaskManager

        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE agent_runs, tasks"))

        self.repository = PostgresTaskRepository(session_factory=self.session_factory)
        self.manager = TaskManager(task_repository=self.repository)

    def test_create_get_list_transition_round_trip_against_real_postgres(self):
        task = self.manager.create("chat.provider", "teste real", agent_id=None)
        self.assertEqual(self.manager.get(task["task_id"])["status"], "pending")
        self.assertEqual(len(self.manager.list()), 1)

        running = self.manager.transition(task["task_id"], "running")
        self.assertEqual(running["status"], "running")

        completed = self.manager.transition(
            task["task_id"], "completed", result={"ok": True, "text": "resposta real"}
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"], {"ok": True, "text": "resposta real"})

    def test_timeout_maps_to_failed_plus_failure_code_in_real_postgres(self):
        from app.db.models import TaskStatus

        task = self.manager.create("chat.provider", "teste")
        self.manager.transition(task["task_id"], "running")
        timed_out = self.manager.transition(task["task_id"], "timeout", error="excedeu")
        self.assertEqual(timed_out["status"], "timeout")

        import uuid

        record = self.repository.get(uuid.UUID(task["task_id"]))
        self.assertEqual(record.status, TaskStatus.FAILED)
        self.assertEqual(record.failure_code, "timeout")

    def test_restart_recovers_state_from_real_postgres(self):
        from app.tasks.manager import TaskManager

        task = self.manager.create("chat.provider", "teste")
        second_manager = TaskManager(task_repository=self.repository)
        self.assertEqual(second_manager.get(task["task_id"])["type"], "chat.provider")

    def test_reconcile_marks_stale_running_task_as_failed_in_real_postgres(self):
        from app.tasks.manager import TaskManager

        task = self.manager.create("chat.provider", "teste")
        self.manager.transition(task["task_id"], "running")

        restarted_manager = TaskManager(task_repository=self.repository)
        # constructing must not have touched anything yet:
        self.assertEqual(restarted_manager.get(task["task_id"])["status"], "running")

        restarted_manager.reconcile()
        self.assertEqual(restarted_manager.get(task["task_id"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
