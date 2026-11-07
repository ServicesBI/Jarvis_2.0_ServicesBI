"""P2 — migração controlada de system/task-state.json para PostgreSQL.

Usa o InMemoryTaskRepository para a maior parte da cobertura (rápido,
determinístico); a validação end-to-end contra jarvis_test fica em
tests/db/test_migrate_task_state_postgres.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db.repositories_memory import InMemoryTaskRepository


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
        "started_at": "2026-08-01T10:00:01+00:00",
        "finished_at": "2026-08-01T10:00:05+00:00",
        "result": {"ok": True},
        "error": None,
    }
    base.update(overrides)
    return base


class MigrationDryRunTests(unittest.TestCase):
    def test_dry_run_validates_without_writing_anything(self):
        from app.db.migrate_task_state import migrate

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, [_legacy_task()])
            repo = InMemoryTaskRepository()

            report = migrate(json_path, task_repository=repo, dry_run=True)

        self.assertEqual(report.total_read, 1)
        self.assertEqual(report.total_inserted, 0)
        self.assertTrue(report.dry_run)
        self.assertEqual(repo.list(), [])


class MigrationRealRunTests(unittest.TestCase):
    def test_818_style_batch_is_accepted_and_ids_are_preserved(self):
        from app.db.migrate_task_state import migrate

        tasks = [
            _legacy_task(task_id=f"{i:032x}", created_at=f"2026-08-01T10:{i%60:02d}:00+00:00")
            for i in range(1, 819)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, tasks)
            repo = InMemoryTaskRepository()

            report = migrate(json_path, task_repository=repo)

        self.assertEqual(report.total_read, 818)
        self.assertEqual(report.total_inserted, 818)
        self.assertEqual(report.total_already_existing, 0)
        self.assertEqual(len(repo.list()), 818)
        first = repo.get(__import__("uuid").UUID("00000000000000000000000000000001"))
        self.assertIsNotNone(first)

    def test_two_timeout_records_map_to_failed_plus_failure_code(self):
        from app.db.migrate_task_state import migrate
        from app.db.models import TaskStatus

        tasks = [
            _legacy_task(task_id="1" * 32, status="timeout", error="Timeout de 60s excedido."),
            _legacy_task(task_id="2" * 32, status="timeout", error="Timeout de 90s excedido."),
            _legacy_task(task_id="3" * 32, status="completed"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, tasks)
            repo = InMemoryTaskRepository()

            report = migrate(json_path, task_repository=repo)

        self.assertEqual(report.total_timeouts_mapped, 2)
        import uuid

        record = repo.get(uuid.UUID("1" * 32))
        self.assertEqual(record.status, TaskStatus.FAILED)
        self.assertEqual(record.failure_code, "timeout")
        self.assertEqual(record.error_text, "Timeout de 60s excedido.")

    def test_result_json_and_error_text_are_preserved(self):
        from app.db.migrate_task_state import migrate

        tasks = [
            _legacy_task(
                task_id="4" * 32,
                status="failed",
                result=None,
                error="boom: alguma coisa quebrou",
            ),
            _legacy_task(
                task_id="5" * 32,
                status="completed",
                result={"ok": True, "artifacts": [{"path": "x.xlsx"}]},
                error=None,
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, tasks)
            repo = InMemoryTaskRepository()
            migrate(json_path, task_repository=repo)

        import uuid

        failed_record = repo.get(uuid.UUID("4" * 32))
        self.assertEqual(failed_record.error_text, "boom: alguma coisa quebrou")
        completed_record = repo.get(uuid.UUID("5" * 32))
        self.assertEqual(
            completed_record.result_json, {"ok": True, "artifacts": [{"path": "x.xlsx"}]}
        )

    def test_null_agent_id_is_preserved_as_null(self):
        from app.db.migrate_task_state import migrate

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, [_legacy_task(task_id="6" * 32, agent_id=None)])
            repo = InMemoryTaskRepository()
            migrate(json_path, task_repository=repo)

        import uuid

        self.assertIsNone(repo.get(uuid.UUID("6" * 32)).agent_id)

    def test_rerun_is_idempotent_and_does_not_duplicate(self):
        from app.db.migrate_task_state import migrate

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, [_legacy_task(task_id="7" * 32)])
            repo = InMemoryTaskRepository()

            first = migrate(json_path, task_repository=repo)
            second = migrate(json_path, task_repository=repo)

        self.assertEqual(first.total_inserted, 1)
        self.assertEqual(second.total_inserted, 0)
        self.assertEqual(second.total_already_existing, 1)
        self.assertEqual(len(repo.list()), 1)

    def test_invalid_record_causes_total_rollback(self):
        from app.db.migrate_task_state import migrate

        tasks = [
            _legacy_task(task_id="8" * 32),
            _legacy_task(task_id="9" * 32, status="not-a-real-status"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, tasks)
            repo = InMemoryTaskRepository()

            report = migrate(json_path, task_repository=repo)

        self.assertEqual(report.total_inserted, 0)
        self.assertGreaterEqual(report.total_failures, 1)
        self.assertEqual(repo.list(), [])

    def test_source_json_file_is_never_modified(self):
        from app.db.migrate_task_state import migrate

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, [_legacy_task(task_id="a" * 32)])
            before = json_path.read_bytes()
            repo = InMemoryTaskRepository()

            migrate(json_path, task_repository=repo)

            after = json_path.read_bytes()
        self.assertEqual(before, after)

    def test_report_includes_checksum_and_counts(self):
        from app.db.migrate_task_state import migrate

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "task-state.json"
            _write_json(json_path, [_legacy_task(task_id="b" * 32)])
            repo = InMemoryTaskRepository()

            report = migrate(json_path, task_repository=repo)

        self.assertEqual(len(report.source_checksum_sha256), 64)
        self.assertIsNotNone(report.started_at)
        self.assertIsNotNone(report.finished_at)


if __name__ == "__main__":
    unittest.main()
