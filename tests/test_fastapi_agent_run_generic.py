"""RED/GREEN da Fase 4C no nivel HTTP: POST /api/agents/{agent_id}/run
generalizado para os 7 especialistas, com MORPHEUS/ZEUS/legado rejeitados.

Usa apenas runners de CLI falsos (mesmo padrao de
tests/test_fastapi_agent_neo_run.py), nunca o Claude/Codex real.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.registry import create_agent_registry
from app.executors.availability import ProviderAvailabilityService
from app.executors.cli import CliExecutionResult
from app.executors.service import ExecutorService
from app.main import create_app
from app.tasks.manager import TaskManager


EXECUTABLE_AGENT_IDS = (
    "oracle",
    "nikita",
    "athena",
    "neo",
    "hephaestus",
    "apollo",
    "trinity",
)

REJECTED_AGENT_IDS = ("morpheus", "zeus", "conclave", "dex", "orion", "foo")


class FakeCliRunner:
    def __init__(
        self,
        result: CliExecutionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result or CliExecutionResult(0, "resposta fake", "")
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        self.calls.append({"arguments": tuple(arguments), "stdin_text": stdin_text})
        if self.error is not None:
            raise self.error
        return self.result


def _mark_available(service: ProviderAvailabilityService, provider: str) -> None:
    service.set_state(
        provider, installed=True, authenticated=True, operational=True, reason="test"
    )


class AgentRunGenericHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _task_manager(self, name: str = "task-state.json") -> TaskManager:
        return TaskManager(
            Path(self.temp_dir.name) / name, agent_registry=self.registry
        )

    def make_client(
        self,
        *,
        mode: str,
        claude_runner: FakeCliRunner,
        codex_runner: FakeCliRunner,
        task_manager: TaskManager | None = None,
        availability_service: ProviderAvailabilityService | None = None,
    ) -> TestClient:
        app = create_app(
            executor_manager=ExecutorService(mode),
            claude_runner=claude_runner,
            codex_runner=codex_runner,
            task_manager=task_manager or self._task_manager(),
            agent_registry=self.registry,
            availability_service=availability_service,
        )
        return TestClient(app)

    def test_all_seven_specialists_execute_and_register_their_own_agent_id(
        self,
    ) -> None:
        for agent_id in EXECUTABLE_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                claude = FakeCliRunner(CliExecutionResult(0, f"ok {agent_id}", ""))
                codex_guard = FakeCliRunner(
                    error=AssertionError("codex não deveria rodar em modo claude")
                )
                task_manager = self._task_manager(f"task-{agent_id}.json")
                with self.make_client(
                    mode="claude",
                    claude_runner=claude,
                    codex_runner=codex_guard,
                    task_manager=task_manager,
                ) as client:
                    response = client.post(
                        f"/api/agents/{agent_id}/run",
                        json={"message": f"tarefa segura para {agent_id}"},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["status"], "completed")

                    tasks = client.get("/api/tasks").json()["tasks"]
                    matching = [t for t in tasks if t["agent_id"] == agent_id]
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0]["status"], "completed")

                stdin_sent = str(claude.calls[0]["stdin_text"])
                self.assertIn(agent_id.upper(), stdin_sent)

    def test_rejected_ids_never_execute(self) -> None:
        claude_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude_guard, codex_runner=codex_guard
        ) as client:
            for agent_id in REJECTED_AGENT_IDS:
                with self.subTest(agent_id=agent_id):
                    response = client.post(
                        f"/api/agents/{agent_id}/run", json={"message": "tarefa"}
                    )
                    self.assertEqual(response.status_code, 404)

            tasks = client.get("/api/tasks").json()["tasks"]
            self.assertEqual(tasks, [])

    def test_codex_mode_is_respected_for_a_specialist(self) -> None:
        claude_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        codex = FakeCliRunner(CliExecutionResult(0, "ok via codex", ""))
        with self.make_client(
            mode="codex", claude_runner=claude_guard, codex_runner=codex
        ) as client:
            calls_before = len(codex.calls)
            response = client.post(
                "/api/agents/hephaestus/run", json={"message": "prepare o ambiente"}
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(codex.calls), calls_before + 1)
        self.assertEqual(len(claude_guard.calls), 0)

    def test_auto_mode_behavior_is_preserved_without_hardcoded_provider(self) -> None:
        availability = ProviderAvailabilityService()
        _mark_available(availability, "codex")
        _mark_available(availability, "claude")
        claude_guard = FakeCliRunner(
            error=AssertionError("AUTO deve preferir codex, claude não deveria rodar")
        )
        codex = FakeCliRunner(CliExecutionResult(0, "ok via auto/codex", ""))
        with self.make_client(
            mode="auto",
            claude_runner=claude_guard,
            codex_runner=codex,
            availability_service=availability,
        ) as client:
            response = client.post(
                "/api/agents/apollo/run", json={"message": "revise a entrega"}
            )
            self.assertEqual(response.status_code, 200)

        self.assertGreaterEqual(len(codex.calls), 1)
        self.assertEqual(len(claude_guard.calls), 0)

    def test_running_one_specialist_leaves_the_others_idle(self) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "ok", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            client.post("/api/agents/trinity/run", json={"message": "tarefa"})
            agents = {
                agent["id"]: agent["status"]
                for agent in client.get("/api/agents").json()["agents"]
            }

        self.assertEqual(agents["trinity"], "idle")
        for agent_id in EXECUTABLE_AGENT_IDS:
            if agent_id != "trinity":
                with self.subTest(agent_id=agent_id):
                    self.assertEqual(agents[agent_id], "idle")
        self.assertEqual(agents["morpheus"], "idle")

    def test_plain_chat_still_works_after_generalization(self) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "resposta normal do chat", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            response = client.post("/api/chat", json={"message": "oi jarvis"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "resposta normal do chat")


if __name__ == "__main__":
    unittest.main()
