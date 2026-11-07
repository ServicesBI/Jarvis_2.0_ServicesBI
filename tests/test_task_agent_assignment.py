from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.registry import UnknownAgentError, create_agent_registry
from app.main import create_app
from app.tasks.manager import TaskManager


INVALID_AGENT_IDS = (
    "dex",
    "orion",
    "aria",
    "dara",
    "sage",
    "gage",
    "quinn",
    "luma",
    "uma",
    "morgan",
    "pax",
    "river",
    "craft",
    "zeus",
    "conclave",
    "foo",
)


class TaskAgentAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "task-state.json"
        self.registry = create_agent_registry()
        self.manager = TaskManager(self.state_path, agent_registry=self.registry)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_task_without_agent_keeps_explicit_none(self) -> None:
        task = self.manager.create("test", "legacy caller")

        self.assertIn("agent_id", task)
        self.assertIsNone(task["agent_id"])

    def test_canonical_agents_are_preserved_on_created_tasks(self) -> None:
        neo = self.manager.create("test", "software", agent_id="neo")
        oracle = self.manager.create("test", "analysis", agent_id="oracle")

        self.assertEqual(neo["agent_id"], "neo")
        self.assertEqual(oracle["agent_id"], "oracle")

    def test_invalid_agent_ids_are_rejected_before_task_creation(self) -> None:
        for agent_id in INVALID_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                before = self.manager.list()
                with self.assertRaises(UnknownAgentError):
                    self.manager.create("test", "invalid", agent_id=agent_id)
                self.assertEqual(self.manager.list(), before)

    def test_submit_accepts_agent_without_changing_legacy_default(self) -> None:
        async def operation() -> dict[str, bool]:
            return {"ok": True}

        async def scenario() -> None:
            assigned = self.manager.submit(
                "test", "assigned", operation, agent_id="neo"
            )
            unassigned = self.manager.submit("test", "unassigned", operation)
            self.assertEqual(assigned["agent_id"], "neo")
            self.assertIsNone(unassigned["agent_id"])
            await self.manager.wait(assigned["task_id"])
            await self.manager.wait(unassigned["task_id"])

        import asyncio

        asyncio.run(scenario())

    def test_persistence_and_summary_preserve_agent_id(self) -> None:
        assigned = self.manager.create("test", "assigned", agent_id="oracle")
        unassigned = self.manager.create("test", "unassigned")

        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))["tasks"]
        self.assertEqual(
            [task["agent_id"] for task in persisted], ["oracle", None]
        )
        summary = self.manager.summary()
        self.assertIsNone(summary["last_task"]["agent_id"])
        self.assertEqual(
            {task["task_id"]: task["agent_id"] for task in summary["active_tasks"]},
            {assigned["task_id"]: "oracle", unassigned["task_id"]: None},
        )

    def test_legacy_persisted_task_is_migrated_to_agent_id_none(self) -> None:
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "tasks": [
                        {
                            "task_id": "legacy",
                            "type": "test",
                            "description": "old",
                            "executor": "local",
                            "status": "completed",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        recovered = TaskManager(self.state_path, agent_registry=self.registry)

        self.assertIsNone(recovered.get("legacy")["agent_id"])
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIsNone(persisted["tasks"][0]["agent_id"])

    def test_tasks_api_lists_assigned_and_unassigned_agent_ids(self) -> None:
        assigned = self.manager.create("test", "assigned", agent_id="oracle")
        unassigned = self.manager.create("test", "unassigned")
        app = create_app(task_manager=self.manager, agent_registry=self.registry)

        with TestClient(app) as client:
            response = client.get("/api/tasks")
            assigned_response = client.get(f"/api/tasks/{assigned['task_id']}")
            agents_response = client.get("/api/agents")

        self.assertEqual(response.status_code, 200)
        by_id = {task["task_id"]: task for task in response.json()["tasks"]}
        self.assertEqual(by_id[assigned["task_id"]]["agent_id"], "oracle")
        self.assertIsNone(by_id[unassigned["task_id"]]["agent_id"])
        self.assertEqual(assigned_response.json()["agent_id"], "oracle")
        self.assertEqual(
            {agent["status"] for agent in agents_response.json()["agents"]},
            {"idle"},
        )

    def test_application_and_task_manager_share_the_injected_registry(self) -> None:
        app = create_app(task_manager=self.manager, agent_registry=self.registry)

        self.assertIs(app.state.agent_registry, self.registry)
        self.assertIs(self.manager.agent_registry, self.registry)


if __name__ == "__main__":
    unittest.main()
