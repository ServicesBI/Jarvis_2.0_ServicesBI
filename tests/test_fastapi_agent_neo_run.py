"""RED/GREEN da Fase 4A no nível HTTP: POST /api/agents/neo/run ponta a ponta.

Usa apenas runners de CLI falsos (mesmo padrão de tests/test_fastapi_claude_chat.py),
nunca o Claude/Codex real.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.registry import create_agent_registry
from app.executors.cli import CliExecutionResult
from app.executors.service import ExecutorService
from app.main import create_app
from app.tasks.manager import TaskManager


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


class AgentNeoRunHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()
        self.task_manager = TaskManager(
            Path(self.temp_dir.name) / "task-state.json",
            agent_registry=self.registry,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_client(
        self, *, mode: str, claude_runner: FakeCliRunner, codex_runner: FakeCliRunner
    ) -> TestClient:
        app = create_app(
            executor_manager=ExecutorService(mode),
            claude_runner=claude_runner,
            codex_runner=codex_runner,
            task_manager=self.task_manager,
            agent_registry=self.registry,
        )
        return TestClient(app)

    def test_neo_run_creates_task_with_agent_id_and_reuses_claude_provider(
        self,
    ) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "codigo implementado", ""))
        codex_guard = FakeCliRunner(
            error=AssertionError("Codex não deveria ser executado em modo claude")
        )
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            response = client.post(
                "/api/agents/neo/run", json={"message": "implemente a função soma"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "completed")

            tasks = client.get("/api/tasks").json()["tasks"]
            neo_tasks = [task for task in tasks if task["agent_id"] == "neo"]
            self.assertEqual(len(neo_tasks), 1)
            self.assertEqual(neo_tasks[0]["status"], "completed")
            self.assertEqual(neo_tasks[0]["type"], "chat.provider")

        self.assertEqual(len(claude.calls), 1)
        self.assertIn("NEO", str(claude.calls[0]["stdin_text"]))
        self.assertIn("implemente a função soma", str(claude.calls[0]["stdin_text"]))

    def test_neo_run_respects_codex_mode_without_hardcoded_provider(self) -> None:
        claude_guard = FakeCliRunner(
            error=AssertionError("Claude não deveria ser executado em modo codex")
        )
        codex = FakeCliRunner(CliExecutionResult(0, "codigo implementado via codex", ""))
        with self.make_client(
            mode="codex", claude_runner=claude_guard, codex_runner=codex
        ) as client:
            calls_before = len(codex.calls)
            response = client.post(
                "/api/agents/neo/run", json={"message": "corrija o bug"}
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(codex.calls), calls_before + 1)
        self.assertEqual(len(claude_guard.calls), 0)

    def test_neo_run_failure_reports_error_and_task_failed(self) -> None:
        claude = FakeCliRunner(error=RuntimeError("cli quebrou"))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            response = client.post("/api/agents/neo/run", json={"message": "tarefa"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "error")

            agents = {
                agent["id"]: agent["status"]
                for agent in client.get("/api/agents").json()["agents"]
            }
            self.assertEqual(agents["neo"], "error")

            tasks = client.get("/api/tasks").json()["tasks"]
            neo_tasks = [task for task in tasks if task["agent_id"] == "neo"]
            self.assertEqual(neo_tasks[0]["status"], "failed")

    def test_other_seven_agents_remain_idle_after_neo_run(self) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "ok", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            client.post("/api/agents/neo/run", json={"message": "tarefa"})
            agents = {
                agent["id"]: agent["status"]
                for agent in client.get("/api/agents").json()["agents"]
            }

        self.assertEqual(agents["neo"], "idle")
        for agent_id in (
            "morpheus",
            "oracle",
            "nikita",
            "athena",
            "hephaestus",
            "apollo",
            "trinity",
        ):
            self.assertEqual(agents[agent_id], "idle")
        self.assertNotIn("zeus", agents)
        self.assertEqual(len(agents), 8)

    def test_no_run_route_exists_for_agents_without_operating_profile(self) -> None:
        # A rota e generica (/api/agents/{agent_id}/run, Fase 4C), entao
        # MORPHEUS/ZEUS/ids legados casam com o path mas sao rejeitados
        # explicitamente (404) dentro do handler, nao por ausencia de rota.
        claude = FakeCliRunner(CliExecutionResult(0, "ok", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            morpheus_response = client.post(
                "/api/agents/morpheus/run", json={"message": "tarefa"}
            )
            self.assertEqual(morpheus_response.status_code, 404)

            zeus_response = client.post(
                "/api/agents/zeus/run", json={"message": "tarefa"}
            )
            self.assertEqual(zeus_response.status_code, 404)

    def test_plain_chat_still_works_unaffected_by_agent_execution(self) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "resposta normal do chat", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            response = client.post("/api/chat", json={"message": "oi jarvis"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "resposta normal do chat")

            tasks = client.get("/api/tasks").json()["tasks"]
            chat_tasks = [task for task in tasks if task["type"] == "chat.provider"]
            self.assertEqual(len(chat_tasks), 1)
            self.assertIsNone(chat_tasks[0]["agent_id"])

    def test_post_tasks_contract_is_untouched(self) -> None:
        claude = FakeCliRunner(CliExecutionResult(0, "ok", ""))
        codex_guard = FakeCliRunner(error=AssertionError("não deveria rodar"))
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=codex_guard
        ) as client:
            response = client.post("/api/tasks", json={"type": "not.supported"})
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
