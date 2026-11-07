"""P2 — migração contra PostgreSQL real (jarvis_test).

Cobre o que o fake in-memory não consegue provar sozinho: um rollback
transacional de VERDADE no banco quando um registro passa na validação
Python mas falha na gravação (ex.: campo grande demais para a coluna).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.config import get_setting

TEST_DATABASE_URL = get_setting("JARVIS_TEST_DATABASE_URL")


def _write_json(path: Path, tasks: list[dict]) -> None:
    path.write_text(
        json.dumps({"version": 1, "tasks": tasks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _legacy_task(**overrides) -> dict:
    base = {
        "task_id": "cd40c4607f7d41aaa4f26ee7a78c6931",
        "type": "chat.provider",
        "description": "desc",
        "executor": "local",
        "display_name": None,
        "agent_id": None,
        "status": "completed",
        "created_at": "2026-08-01T10:00:00+00:00",
        "started_at": None,
        "finished_at": "2026-08-01T10:00:05+00:00",
        "result": {"ok": True},
        "error": None,
    }
    base.update(overrides)
    return base


@unittest.skipUnless(TEST_DATABASE_URL, "JARVIS_TEST_DATABASE_URL não configurada.")
class MigrateTaskStatePostgresTests(unittest.TestCase):
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

        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE agent_runs, tasks"))

    def test_migrate_against_real_postgres_inserts_and_is_idempotent(self):
        from app.db.migrate_task_state import migrate
        from app.db.repositories_postgres import PostgresTaskRepository
        from app.db.uow import unit_of_work

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(
                json_path,
                [
                    _legacy_task(task_id="1" * 32, status="completed"),
                    _legacy_task(task_id="2" * 32, status="timeout"),
                    _legacy_task(task_id="3" * 32, status="cancelled"),
                ],
            )

            with unit_of_work(self.session_factory) as session:
                repo = PostgresTaskRepository(session=session)
                first_report = migrate(json_path, task_repository=repo)

            self.assertEqual(first_report.total_inserted, 3)
            self.assertEqual(first_report.total_timeouts_mapped, 1)

            with unit_of_work(self.session_factory) as session:
                repo = PostgresTaskRepository(session=session)
                second_report = migrate(json_path, task_repository=repo)

            self.assertEqual(second_report.total_inserted, 0)
            self.assertEqual(second_report.total_already_existing, 3)

    def test_a_field_too_long_for_the_column_rolls_back_the_whole_batch(self):
        from sqlalchemy.exc import DataError

        from app.db.migrate_task_state import migrate
        from app.db.repositories_postgres import PostgresTaskRepository
        from app.db.uow import unit_of_work

        oversized_type = "x" * 500  # coluna type é VARCHAR(120)
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(
                json_path,
                [
                    _legacy_task(task_id="4" * 32, status="completed"),
                    _legacy_task(task_id="5" * 32, status="completed", type=oversized_type),
                ],
            )

            with self.assertRaises(DataError):
                with unit_of_work(self.session_factory) as session:
                    repo = PostgresTaskRepository(session=session)
                    migrate(json_path, task_repository=repo)

        from sqlalchemy import text

        with self.engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
        self.assertEqual(count, 0, "rollback deveria ter desfeito TODO o lote, inclusive o registro válido")


if __name__ == "__main__":
    unittest.main()
