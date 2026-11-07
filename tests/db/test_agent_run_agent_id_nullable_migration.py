"""Módulo 5A1 — prova de migration real: agent_runs.agent_id NOT NULL -> NULLABLE.

Só roda contra o banco de TESTE (JARVIS_TEST_DATABASE_URL). Sem essa
variável, a suíte inteira faz SKIP explícito — nunca usa
JARVIS_DATABASE_URL de produção, nunca cai para SQLite.
"""

from __future__ import annotations

import unittest

from app.core.config import get_setting

TEST_DATABASE_URL = get_setting("JARVIS_TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "JARVIS_TEST_DATABASE_URL não configurada — integração PostgreSQL real "
    "requer provisionamento manual de um banco de teste isolado.",
)
class AgentRunAgentIdNullableMigrationTests(unittest.TestCase):
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

    def _agent_id_column_nullable(self) -> bool:
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        columns = inspector.get_columns("agent_runs")
        (agent_id_column,) = [c for c in columns if c["name"] == "agent_id"]
        return bool(agent_id_column["nullable"])

    def test_upgrade_produces_nullable_column(self) -> None:
        """Prova no PostgreSQL real (não só na metadata do ORM) que a
        migration 0003, já aplicada por upgrade_to_head no setUpClass,
        removeu o NOT NULL de agent_runs.agent_id."""
        self.assertTrue(self._agent_id_column_nullable())

    def test_downgrade_restores_not_null_in_a_clean_scenario(self) -> None:
        """Prova o downgrade documentado na migration 0003: em um cenário
        SEM nenhuma linha agent_id=NULL (garantido pelo TRUNCATE em setUp),
        o downgrade para 0002 restaura NOT NULL com sucesso. Sempre volta a
        aplicar upgrade_to_head no final (try/finally), preservando o banco
        de teste no estado esperado pelos demais testes desta suíte."""
        from alembic import command

        from app.db.migration_runner import _config, _database_url_env

        self.assertTrue(
            self._agent_id_column_nullable(),
            "pré-condição: banco deveria estar em head (nullable=True) antes do downgrade",
        )

        try:
            with _database_url_env(TEST_DATABASE_URL):
                command.downgrade(_config(), "0002")
            self.assertFalse(
                self._agent_id_column_nullable(),
                "downgrade para 0002 deveria restaurar NOT NULL",
            )
        finally:
            with _database_url_env(TEST_DATABASE_URL):
                command.upgrade(_config(), "head")


if __name__ == "__main__":
    unittest.main()
