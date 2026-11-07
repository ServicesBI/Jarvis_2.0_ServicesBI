"""Regressao dos contratos auxiliares migrados para o FastAPI."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.tasks.manager import TaskManager


class FastAPIAuxiliaryRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.task_manager = TaskManager(Path(cls.temp_dir.name) / "task-state.json")
        cls.app = create_app(task_manager=cls.task_manager)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_cowork_lifecycle(self):
        self.assertEqual(self.client.post("/api/cowork/start", json={}).json()["status"], "started")
        self.assertEqual(self.client.post("/api/cowork/start", json={}).json()["status"], "already running")
        self.assertTrue(self.client.get("/api/cowork/status").json()["active"])
        self.assertEqual(self.client.post("/api/cowork/stop", json={}).json()["status"], "stopped")

    def test_files_and_traversal_contract(self):
        response = self.client.get("/api/files")
        self.assertEqual(response.status_code, 200)
        self.assertIn("files", response.json())
        self.assertEqual(self.client.get("/api/files/view", params={"path": "../outside.txt"}).status_code, 404)
        self.assertEqual(self.client.get("/api/files/download", params={"path": "../outside.txt"}).status_code, 404)

    def test_attachment_missing_file_is_contract_400(self):
        self.assertEqual(self.client.post("/api/attach").status_code, 400)

    def test_obsidian_and_memory_metadata_are_read_only_and_available(self):
        stats = self.client.get("/api/obsidian/stats")
        memory = self.client.get("/api/memory/status")
        tree = self.client.get("/api/obsidian/tree")
        self.assertEqual((stats.status_code, memory.status_code, tree.status_code), (200, 200, 200))
        self.assertIn("connected", stats.json())
        self.assertEqual(memory.json()["totalLayers"], 3)
        self.assertIn("tree", tree.json())

    def test_optional_integrations_respond_without_static_fallback(self):
        connections = self.client.get("/api/connections/providers")
        balance = self.client.get("/api/agenda/balance")
        self.assertEqual(connections.status_code, 200)
        self.assertEqual(set(connections.json()), {"providers", "categories", "checkedAt"})
        self.assertEqual(balance.status_code, 200)
        self.assertIn("available", balance.json())

    def test_pet_mic_event_is_published(self):
        events = []

        async def publish(event):
            events.append(event)

        self.app.state.notification_broker.publish = publish
        response = self.client.post("/api/pet/mic-state", json={"active": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, [{"type": "pet-mic", "active": True}])


if __name__ == "__main__":
    unittest.main()
