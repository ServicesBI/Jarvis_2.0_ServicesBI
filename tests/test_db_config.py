"""P0 — contrato de configuração do banco: JARVIS_DATABASE_URL.

Nenhum destes testes conecta a um banco real. `create_engine()` do SQLAlchemy
não abre conexão até o primeiro uso, então instanciar o Engine é seguro e local.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_setting
from app.main import create_app


class DatabaseUrlConfigTests(unittest.TestCase):
    def test_database_url_is_readable_via_existing_get_setting(self) -> None:
        with patch.dict(os.environ, {"JARVIS_DATABASE_URL": "postgresql+psycopg://u:p@localhost/jarvis"}):
            self.assertEqual(
                get_setting("JARVIS_DATABASE_URL"),
                "postgresql+psycopg://u:p@localhost/jarvis",
            )

    def test_test_database_url_is_readable_via_existing_get_setting(self) -> None:
        with patch.dict(os.environ, {"JARVIS_TEST_DATABASE_URL": "postgresql+psycopg://u:p@localhost/jarvis_test"}):
            self.assertEqual(
                get_setting("JARVIS_TEST_DATABASE_URL"),
                "postgresql+psycopg://u:p@localhost/jarvis_test",
            )


class CreateDatabaseEngineTests(unittest.TestCase):
    def test_missing_url_raises_explicit_error(self) -> None:
        from app.db.engine import DatabaseNotConfiguredError, create_database_engine

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_DATABASE_URL", None)
            with patch("app.db.engine.get_setting", return_value=None):
                with self.assertRaises(DatabaseNotConfiguredError):
                    create_database_engine()

    def test_explicit_url_is_used_when_provided(self) -> None:
        from app.db.engine import create_database_engine

        engine = create_database_engine("postgresql+psycopg://u:p@localhost/jarvis")
        self.assertIn("postgresql", str(engine.url))

    def test_sqlite_url_is_rejected_never_used_as_fallback(self) -> None:
        from app.db.engine import create_database_engine

        with self.assertRaises(ValueError):
            create_database_engine("sqlite:///local.db")

    def test_env_configured_url_is_picked_up_without_explicit_argument(self) -> None:
        from app.db.engine import create_database_engine

        with patch(
            "app.db.engine.get_setting",
            return_value="postgresql+psycopg://u:p@localhost/jarvis",
        ):
            engine = create_database_engine()
        self.assertIn("postgresql", str(engine.url))

    def test_session_factory_is_bound_to_the_engine(self) -> None:
        from app.db.engine import create_database_engine, create_session_factory

        engine = create_database_engine("postgresql+psycopg://u:p@localhost/jarvis")
        factory = create_session_factory(engine)
        session = factory()
        try:
            self.assertIs(session.bind, engine)
        finally:
            session.close()


class RuntimeUnaffectedWithoutDatabaseUrlTests(unittest.TestCase):
    def test_app_still_boots_with_no_database_url_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_DATABASE_URL", None)
            with TestClient(create_app()) as client:
                response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
