"""P0 — contrato de schema de tasks/agent_runs.

Estes testes inspecionam apenas o objeto `Table`/metadata do SQLAlchemy —
nenhum Engine, nenhuma conexão, nenhum banco real é usado.
"""

from __future__ import annotations

import unittest

from sqlalchemy import UniqueConstraint


class TaskStatusEnumTests(unittest.TestCase):
    def test_approved_values_only_and_no_timeout(self) -> None:
        from app.db.models import TaskStatus

        values = {status.value for status in TaskStatus}
        self.assertEqual(
            values,
            {"pending", "running", "waiting_approval", "completed", "failed", "cancelled"},
        )
        self.assertNotIn("timeout", values)


class AgentRunStatusEnumTests(unittest.TestCase):
    def test_approved_values_only_and_no_timeout(self) -> None:
        from app.db.models import AgentRunStatus

        values = {status.value for status in AgentRunStatus}
        self.assertEqual(
            values,
            {"pending", "running", "completed", "failed", "cancelled"},
        )
        self.assertNotIn("timeout", values)


class TaskRecordSchemaTests(unittest.TestCase):
    def test_table_name(self) -> None:
        from app.db.models import TaskRecord

        self.assertEqual(TaskRecord.__tablename__, "tasks")

    def test_expected_columns_exist(self) -> None:
        from app.db.models import TaskRecord

        columns = set(TaskRecord.__table__.columns.keys())
        expected = {
            "id",
            "type",
            "description",
            "executor",
            "display_name",
            "agent_id",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "result_json",
            "error_text",
            "failure_code",
        }
        self.assertTrue(expected.issubset(columns), columns)

    def test_id_is_primary_key(self) -> None:
        from app.db.models import TaskRecord

        self.assertTrue(TaskRecord.__table__.columns["id"].primary_key)

    def test_required_columns_are_not_nullable(self) -> None:
        from app.db.models import TaskRecord

        table = TaskRecord.__table__
        for column_name in ("type", "status", "created_at"):
            with self.subTest(column=column_name):
                self.assertFalse(table.columns[column_name].nullable)

    def test_optional_columns_are_nullable(self) -> None:
        from app.db.models import TaskRecord

        table = TaskRecord.__table__
        for column_name in (
            "agent_id",
            "started_at",
            "finished_at",
            "result_json",
            "error_text",
            "failure_code",
        ):
            with self.subTest(column=column_name):
                self.assertTrue(table.columns[column_name].nullable)

    def test_status_index_exists(self) -> None:
        from app.db.models import TaskRecord

        index_columns = {
            frozenset(col.name for col in index.columns)
            for index in TaskRecord.__table__.indexes
        }
        self.assertIn(frozenset({"status"}), index_columns)


class AgentRunRecordSchemaTests(unittest.TestCase):
    def test_table_name(self) -> None:
        from app.db.models import AgentRunRecord

        self.assertEqual(AgentRunRecord.__tablename__, "agent_runs")

    def test_expected_columns_exist(self) -> None:
        from app.db.models import AgentRunRecord

        columns = set(AgentRunRecord.__table__.columns.keys())
        expected = {
            "id",
            "task_id",
            "attempt_number",
            "execution_key",
            "agent_id",
            "provider",
            "model_profile",
            "status",
            "input_text",
            "context_json",
            "operating_instructions_ref",
            "output_text",
            "structured_result_json",
            "summary",
            "error_text",
            "failure_code",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        }
        self.assertTrue(expected.issubset(columns), columns)

    def test_task_id_foreign_key_targets_tasks(self) -> None:
        from app.db.models import AgentRunRecord

        column = AgentRunRecord.__table__.columns["task_id"]
        self.assertTrue(column.foreign_keys)
        target = next(iter(column.foreign_keys)).target_fullname
        self.assertEqual(target, "tasks.id")

    def test_unique_constraint_on_task_id_and_attempt_number(self) -> None:
        from app.db.models import AgentRunRecord

        unique_column_sets = {
            frozenset(col.name for col in constraint.columns)
            for constraint in AgentRunRecord.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertIn(frozenset({"task_id", "attempt_number"}), unique_column_sets)

    def test_unique_constraint_on_execution_key(self) -> None:
        from app.db.models import AgentRunRecord

        unique_column_sets = {
            frozenset(col.name for col in constraint.columns)
            for constraint in AgentRunRecord.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertIn(frozenset({"execution_key"}), unique_column_sets)

    def test_execution_key_is_required(self) -> None:
        from app.db.models import AgentRunRecord

        self.assertFalse(
            AgentRunRecord.__table__.columns["execution_key"].nullable
        )

    def test_attempt_number_is_required(self) -> None:
        from app.db.models import AgentRunRecord

        self.assertFalse(
            AgentRunRecord.__table__.columns["attempt_number"].nullable
        )

    def test_agent_id_status_index_exists(self) -> None:
        from app.db.models import AgentRunRecord

        index_columns = {
            frozenset(col.name for col in index.columns)
            for index in AgentRunRecord.__table__.indexes
        }
        self.assertIn(frozenset({"agent_id", "status"}), index_columns)

    def test_relationship_to_task_record(self) -> None:
        from app.db.models import AgentRunRecord, TaskRecord

        self.assertTrue(hasattr(AgentRunRecord, "task"))
        self.assertTrue(hasattr(TaskRecord, "agent_runs"))

    def test_agent_id_is_nullable(self) -> None:
        """Módulo 5A1: AgentRun representa uma tentativa de execução de uma
        Task, não obrigatoriamente a execução de uma persona/agente — chat
        comum/AUTO (a maioria das Tasks reais hoje) não tem agent_id."""
        from app.db.models import AgentRunRecord

        self.assertTrue(AgentRunRecord.__table__.columns["agent_id"].nullable)

    def test_other_columns_unaffected_by_agent_id_nullable_change(self) -> None:
        from app.db.models import AgentRunRecord

        table = AgentRunRecord.__table__
        self.assertTrue(table.columns["provider"].nullable)
        self.assertTrue(table.columns["model_profile"].nullable)
        self.assertFalse(table.columns["status"].nullable)
        self.assertFalse(table.columns["attempt_number"].nullable)
        self.assertFalse(table.columns["execution_key"].nullable)


class MetadataScopeTests(unittest.TestCase):
    def test_only_tasks_and_agent_runs_are_registered_this_phase(self) -> None:
        from app.db.models import Base

        self.assertEqual(set(Base.metadata.tables.keys()), {"tasks", "agent_runs"})


if __name__ == "__main__":
    unittest.main()
