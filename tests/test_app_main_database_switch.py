"""P2 — Precondição C: importar/construir app.main nunca causa I/O de banco.

`create_engine()` do SQLAlchemy é preguiçoso (não conecta na criação), então
mesmo apontando JARVIS_DATABASE_URL para um host que não existe, apenas
*construir* a app (sem dar TestClient(app).__enter__()/startup) não pode
levantar erro de conexão. A reconciliação real só roda no startup event.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.main import create_app


class DefaultsToFileModeWithoutOperationalUrlTests(unittest.TestCase):
    def test_no_database_url_defaults_to_file_backed_task_manager(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_DATABASE_URL", None)
            app = create_app()
        self.assertIsNotNone(app.state.task_manager.state_path)

    def test_test_database_url_alone_does_not_activate_repository_mode(self):
        """JARVIS_TEST_DATABASE_URL nunca deve, por si só, mudar o backend
        do TaskManager de produção — só JARVIS_DATABASE_URL controla isso."""

        with patch.dict(
            os.environ,
            {"JARVIS_TEST_DATABASE_URL": "postgresql+psycopg://u:p@localhost/jarvis_test"},
            clear=False,
        ):
            os.environ.pop("JARVIS_DATABASE_URL", None)
            app = create_app()
        self.assertIsNotNone(app.state.task_manager.state_path)


class RepositoryModeConstructionIsLazyTests(unittest.TestCase):
    def test_constructing_app_with_unreachable_database_url_does_not_connect(self):
        """Aponta para um host que não existe: se create_app() tentasse
        conectar durante a construção, isso levantaria um erro de conexão
        aqui mesmo, síncrono, sem precisar de TestClient/startup event."""

        with patch.dict(
            os.environ,
            {
                "JARVIS_DATABASE_URL": (
                    "postgresql+psycopg://u:p@host-que-nao-existe.invalid:5432/jarvis"
                )
            },
            clear=False,
        ):
            app = create_app()  # não deve levantar

        self.assertIsNone(app.state.task_manager.state_path)

    def test_reconcile_startup_handler_is_registered_for_every_owned_task_manager(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_DATABASE_URL", None)
            file_mode_app = create_app()
        file_mode_startup_names = {
            handler.__name__ for handler in file_mode_app.router.on_startup
        }
        self.assertIn("reconcile_task_manager", file_mode_startup_names)

        with patch.dict(
            os.environ,
            {"JARVIS_DATABASE_URL": "postgresql+psycopg://u:p@host-que-nao-existe.invalid/jarvis"},
            clear=False,
        ):
            repository_mode_app = create_app()
        repository_mode_startup_names = {
            handler.__name__ for handler in repository_mode_app.router.on_startup
        }
        self.assertIn("reconcile_task_manager", repository_mode_startup_names)

    def test_explicit_task_manager_override_never_triggers_the_database_switch(self):
        """Quando o caller já passa task_manager=, JARVIS_DATABASE_URL é
        ignorada por completo — nenhum reconcile é registrado por baixo."""

        import tempfile
        from pathlib import Path

        from app.tasks.manager import TaskManager

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "task-state.json")
            with patch.dict(
                os.environ,
                {"JARVIS_DATABASE_URL": "postgresql+psycopg://u:p@host-que-nao-existe.invalid/jarvis"},
                clear=False,
            ):
                app = create_app(task_manager=manager)
        self.assertIs(app.state.task_manager, manager)
        startup_names = {handler.__name__ for handler in app.router.on_startup}
        self.assertIn("reconcile_task_manager", startup_names)


if __name__ == "__main__":
    unittest.main()
