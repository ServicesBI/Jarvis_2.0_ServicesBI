"""P2 — compatibilidade pública do TaskManager em modo repository.

Prova que ActionEngine, /api/tasks (GET/POST/cancel) e o formato de task_id
continuam funcionando exatamente como no modo arquivo, agora com um
InMemoryTaskRepository por baixo (rápido, sem PostgreSQL real necessário
para provar o contrato HTTP/callers).
"""

from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from app.actions.excel import create_excel_definition
from app.actions.models import ActionRequest
from app.actions.registry import ActionRegistry
from app.actions.engine import ActionEngine
from app.db.repositories_memory import InMemoryTaskRepository
from app.main import create_app
from app.tasks.manager import TaskManager


class TaskIdFormatCompatibilityTests(unittest.TestCase):
    def test_task_id_is_32_char_hex_like_the_legacy_uuid4_hex_format(self):
        manager = TaskManager(task_repository=InMemoryTaskRepository())
        task = manager.create("chat.provider", "teste")
        task_id = task["task_id"]
        self.assertEqual(len(task_id), 32)
        # deve ser aceitável tanto para lookup direto quanto para reconstruir
        # o UUID original (prova de que não há perda de informação no id).
        self.assertEqual(uuid.UUID(task_id).hex, task_id)
        self.assertEqual(manager.get(task_id)["task_id"], task_id)


class ActionEngineBackwardCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_engine_submit_completes_through_repository_backed_manager(self):
        manager = TaskManager(task_repository=InMemoryTaskRepository())
        registry = ActionRegistry()
        registry.register(create_excel_definition())
        engine = ActionEngine(registry, manager)

        task = engine.submit(
            ActionRequest(
                action="excel.create",
                arguments={"filename": "relatorio.xlsx", "headers": ["a"], "rows": [["1"]]},
                source="api",
            )
        )
        self.assertEqual(task["status"], "pending")
        finished = await manager.wait(task["task_id"])
        self.assertIn(finished["status"], {"completed", "failed"})
        self.assertEqual(finished["task_id"], task["task_id"])


class HttpTaskApiBackwardCompatTests(unittest.TestCase):
    def setUp(self):
        self.manager = TaskManager(task_repository=InMemoryTaskRepository())
        self.client = TestClient(create_app(task_manager=self.manager))

    def tearDown(self):
        self.client.close()

    def test_get_tasks_lists_repository_backed_tasks(self):
        self.manager.create("chat.provider", "teste")
        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["tasks"]), 1)

    def test_get_task_by_id_returns_the_same_shape_as_file_mode(self):
        created = self.manager.create("chat.provider", "teste")
        response = self.client.get(f"/api/tasks/{created['task_id']}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {
                "task_id", "type", "description", "executor", "display_name",
                "agent_id", "status", "created_at", "started_at", "finished_at",
                "result", "error",
            },
        )

    def test_get_unknown_task_is_404(self):
        response = self.client.get("/api/tasks/" + "0" * 32)
        self.assertEqual(response.status_code, 404)

    def test_cancel_route_cancels_pending_task(self):
        created = self.manager.create("chat.provider", "teste")
        response = self.client.post(f"/api/tasks/{created['task_id']}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

    def test_cancel_unknown_task_is_404(self):
        response = self.client.post("/api/tasks/" + "0" * 32 + "/cancel")
        self.assertEqual(response.status_code, 404)

    def test_post_tasks_excel_create_route_still_works(self):
        response = self.client.post(
            "/api/tasks",
            json={
                "type": "excel.create",
                "payload": {"filename": "x.xlsx", "headers": ["a"], "rows": [["1"]]},
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "pending")

    def test_summary_route_still_works(self):
        self.manager.create("chat.provider", "teste")
        response = self.client.get("/api/tasks/summary")
        self.assertEqual(response.status_code, 200)
        self.assertIn("total", response.json())


class TimeoutSemanticsBackwardCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_path_reports_public_status_timeout(self):
        import asyncio

        manager = TaskManager(task_repository=InMemoryTaskRepository())

        async def slow_operation():
            await asyncio.sleep(10)
            return {"ok": True}

        task = manager.submit(
            "chat.provider", "teste", slow_operation, timeout=0.05
        )
        finished = await manager.wait(task["task_id"])
        self.assertEqual(finished["status"], "timeout")
        self.assertIn("Timeout", finished["error"])


if __name__ == "__main__":
    unittest.main()
