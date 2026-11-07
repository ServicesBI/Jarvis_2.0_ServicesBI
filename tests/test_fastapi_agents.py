from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.registry import create_agent_registry
from app.executors.availability import ProviderAvailabilityService
from app.executors.service import ExecutorService
from app.main import create_app
from app.providers.factory import create_provider_manager
from app.tasks.manager import TaskManager


EXPECTED_IDS = [
    "morpheus", "oracle", "nikita", "athena", "neo", "hephaestus", "apollo", "trinity"
]
EXPECTED_FIELDS = {
    "id", "name", "role", "description", "status", "canonical_persona"
}


class AgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.executor = ExecutorService("claude")
        self.availability = ProviderAvailabilityService()
        self.tasks = TaskManager(Path(self.temp_dir.name) / "tasks.json")
        self.registry = create_agent_registry()
        self.client = TestClient(
            create_app(
                executor_manager=self.executor,
                availability_service=self.availability,
                provider_manager=create_provider_manager(),
                task_manager=self.tasks,
                agent_registry=self.registry,
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_get_agents_returns_exact_catalog_and_payload_contract(self) -> None:
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 8)
        self.assertEqual([item["id"] for item in payload["agents"]], EXPECTED_IDS)
        self.assertTrue(all(set(item) == EXPECTED_FIELDS for item in payload["agents"]))
        self.assertTrue(all(item["status"] == "idle" for item in payload["agents"]))
        self.assertEqual(
            payload["agents"][0]["canonical_persona"],
            "obsidian-template/Agentes/Morpheus — Orchestrator.md",
        )

    def test_only_get_is_exposed(self) -> None:
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)("/api/agents").status_code, 405)

    def test_get_agents_has_no_operational_side_effects(self) -> None:
        before_mode = self.executor.get_mode()
        before_availability = {
            provider: self.availability.get_state(provider)
            for provider in ("codex", "claude", "openai")
        }
        before_tasks = self.tasks.summary()

        response = self.client.get("/api/agents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.executor.get_mode(), before_mode)
        self.assertEqual(
            {provider: self.availability.get_state(provider) for provider in before_availability},
            before_availability,
        )
        self.assertEqual(self.tasks.summary(), before_tasks)
        self.assertIs(self.client.app.state.agent_registry, self.registry)


if __name__ == "__main__":
    unittest.main()
