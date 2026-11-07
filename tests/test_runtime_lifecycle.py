"""Regressões bounded do Módulo 1A — Runtime / Lifecycle."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import create_app
from app.tasks.manager import TaskManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EntrypointContractTests(unittest.TestCase):
    def test_app_main_has_no_executable_main_guard_or_uvicorn_run(self) -> None:
        source = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        main_guards = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ]
        uvicorn_runs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "uvicorn"
            and node.func.attr == "run"
        ]

        self.assertEqual(main_guards, [])
        self.assertEqual(uvicorn_runs, [])

    def test_launcher_still_starts_run_py(self) -> None:
        launcher = (PROJECT_ROOT / "Ligar JARVIS.bat").read_text(encoding="utf-8")
        self.assertIn('"%PYTHON_EXE%" run.py', launcher)


class FileTaskManagerCompositionTests(unittest.TestCase):
    @staticmethod
    def _write_running_task(state_path: Path) -> str:
        task_id = "a" * 32
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "task_id": task_id,
                            "type": "test",
                            "description": "running before restart",
                            "status": "running",
                            "created_at": "2026-09-07T00:00:00+00:00",
                            "started_at": "2026-09-07T00:00:01+00:00",
                            "finished_at": None,
                            "result": None,
                            "error": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return task_id

    def test_constructing_file_manager_loads_without_reconcile_or_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            task_id = self._write_running_task(state_path)
            original = state_path.read_bytes()

            manager = TaskManager(state_path)

            self.assertEqual(manager.get(task_id)["status"], "running")
            self.assertEqual(state_path.read_bytes(), original)

    def test_create_app_does_not_reconcile_or_persist_during_composition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            task_id = self._write_running_task(state_path)
            original = state_path.read_bytes()
            manager = TaskManager(state_path)

            application = create_app(task_manager=manager)

            self.assertIs(application.state.task_manager, manager)
            self.assertEqual(manager.get(task_id)["status"], "running")
            self.assertEqual(state_path.read_bytes(), original)

    def test_explicit_reconcile_recovers_and_persists_file_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            task_id = self._write_running_task(state_path)
            manager = TaskManager(state_path)

            manager.reconcile()

            self.assertEqual(manager.get(task_id)["status"], "failed")
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["tasks"][0]["status"], "failed")
            self.assertIn("application restart", persisted["tasks"][0]["error"])

    def test_file_reconcile_is_registered_and_runs_on_fastapi_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            task_id = self._write_running_task(state_path)
            manager = TaskManager(state_path)
            application = create_app(task_manager=manager)

            startup_names = {handler.__name__ for handler in application.router.on_startup}
            self.assertIn("reconcile_task_manager", startup_names)

            with TestClient(application):
                self.assertEqual(manager.get(task_id)["status"], "failed")


class FastApiShutdownLifecycleTests(unittest.TestCase):
    def test_fastapi_shutdown_calls_task_manager_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "task-state.json")
            manager.shutdown = AsyncMock()
            application = create_app(task_manager=manager)

            with TestClient(application):
                pass

            manager.shutdown.assert_awaited_once_with()


class WindowsStopContractTests(unittest.TestCase):
    def test_normal_stop_requests_graceful_shutdown_and_waits_bounded(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "jarvis-python-control.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("/api/jarvis/shutdown", script)
        self.assertRegex(script, r"Invoke-RestMethod[\s\S]+-Method\s+Post")
        self.assertIn("[DateTime]::UtcNow.AddSeconds(", script)
        self.assertNotRegex(script, r"Stop-Process[\s\S]*-Force")

    def test_identity_check_uses_jarvis_server_contract_not_global_health(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "jarvis-python-control.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('$health.components.server.status -eq "ok"', script)
        self.assertNotIn('$health.status -eq "healthy"', script)


if __name__ == "__main__":
    unittest.main()
