"""Precondição A da P2: PostgreSQL rejeita status fora do enum aprovado.

Insere via SQL cru (bypassa a validação Python do Enum) para provar que a
proteção existe no próprio banco, não só na camada ORM.
"""

from __future__ import annotations

import unittest
import uuid

from app.core.config import get_setting

TEST_DATABASE_URL = get_setting("JARVIS_TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "JARVIS_TEST_DATABASE_URL não configurada.",
)
class StatusCheckConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.db.engine import create_database_engine, create_session_factory
        from app.db.migration_runner import upgrade_to_head

        cls.engine = create_database_engine(TEST_DATABASE_URL)
        upgrade_to_head(TEST_DATABASE_URL)
        cls.session_factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self._session = self.session_factory()

    def tearDown(self) -> None:
        self._session.rollback()
        self._session.close()

    def test_invalid_task_status_is_rejected_by_the_database(self) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        task_id = uuid.uuid4()
        with self.assertRaises(IntegrityError):
            self._session.execute(
                text(
                    "INSERT INTO tasks (id, type, status, created_at) "
                    "VALUES (:id, 'chat.provider', 'not-a-real-status', now())"
                ),
                {"id": task_id},
            )
            self._session.flush()

    def test_legacy_timeout_is_rejected_as_a_task_status(self) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        task_id = uuid.uuid4()
        with self.assertRaises(IntegrityError):
            self._session.execute(
                text(
                    "INSERT INTO tasks (id, type, status, created_at) "
                    "VALUES (:id, 'chat.provider', 'timeout', now())"
                ),
                {"id": task_id},
            )
            self._session.flush()

    def test_valid_task_status_is_accepted(self) -> None:
        from sqlalchemy import text

        task_id = uuid.uuid4()
        self._session.execute(
            text(
                "INSERT INTO tasks (id, type, status, created_at) "
                "VALUES (:id, 'chat.provider', 'pending', now())"
            ),
            {"id": task_id},
        )
        self._session.flush()

    def test_invalid_agent_run_status_is_rejected_by_the_database(self) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        task_id = uuid.uuid4()
        self._session.execute(
            text(
                "INSERT INTO tasks (id, type, status, created_at) "
                "VALUES (:id, 'chat.provider', 'pending', now())"
            ),
            {"id": task_id},
        )
        run_id = uuid.uuid4()
        with self.assertRaises(IntegrityError):
            self._session.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(id, task_id, attempt_number, execution_key, agent_id, status, created_at, updated_at) "
                    "VALUES (:rid, :tid, 1, :key, 'neo', 'not-a-real-status', now(), now())"
                ),
                {"rid": run_id, "tid": task_id, "key": f"key-{run_id}"},
            )
            self._session.flush()

    def test_waiting_approval_is_accepted_only_for_task_not_agent_run(self) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        task_id = uuid.uuid4()
        self._session.execute(
            text(
                "INSERT INTO tasks (id, type, status, created_at) "
                "VALUES (:id, 'chat.provider', 'waiting_approval', now())"
            ),
            {"id": task_id},
        )
        self._session.flush()
        self._session.rollback()

        task_id_2 = uuid.uuid4()
        self._session.execute(
            text(
                "INSERT INTO tasks (id, type, status, created_at) "
                "VALUES (:id, 'chat.provider', 'pending', now())"
            ),
            {"id": task_id_2},
        )
        run_id = uuid.uuid4()
        with self.assertRaises(IntegrityError):
            self._session.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(id, task_id, attempt_number, execution_key, agent_id, status, created_at, updated_at) "
                    "VALUES (:rid, :tid, 1, :key, 'neo', 'waiting_approval', now(), now())"
                ),
                {"rid": run_id, "tid": task_id_2, "key": f"key-{run_id}"},
            )
            self._session.flush()


if __name__ == "__main__":
    unittest.main()
