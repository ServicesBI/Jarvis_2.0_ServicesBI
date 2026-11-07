"""RED/GREEN da Fase 5A no nivel HTTP: POST /api/agents/morpheus/plan.

Usa apenas um runner de CLI falso que roteia a resposta pelo marcador de
identidade presente no operating_prompt de cada agente (ex.: "ORACLE"),
nunca o Claude/Codex real. Mesmo padrao de tests/test_fastapi_agent_run_generic.py.
"""

from __future__ import annotations

import json
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


def _plan_payload(steps: list[dict], **overrides) -> dict:
    payload = {
        "objective": "Criar um ERP de Compras",
        "summary": "Analise inicial antes da implementacao",
        "steps": steps,
        "requires_approval_before_execution": True,
    }
    payload.update(overrides)
    return payload


def _step(step_id: str, agent_id: str, **overrides) -> dict:
    base = {
        "step_id": step_id,
        "agent_id": agent_id,
        "objective": f"tarefa de {agent_id}",
        "phase": "analysis",
        "requires_approval": False,
    }
    base.update(overrides)
    return base


class RoutedCliRunner:
    """Roteia a resposta pelo marcador de identidade no operating_prompt."""

    def __init__(self, responses_by_marker: dict[str, str]) -> None:
        self._responses = responses_by_marker
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd=None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        self.calls.append({"stdin_text": stdin_text})
        text = stdin_text or ""
        for marker, response in self._responses.items():
            if marker in text:
                return CliExecutionResult(0, response, "")
        raise AssertionError(f"nenhuma resposta roteada para stdin: {text[:300]}")


class AlwaysFailsCliRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, arguments=(), *, timeout=None, cwd=None, stdin_text=None):
        self.calls.append({"stdin_text": stdin_text})
        raise AssertionError("este runner não deveria ser chamado")


class MorpheusPlanHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _task_manager(self, name: str = "tasks.json") -> TaskManager:
        return TaskManager(
            Path(self.temp_dir.name) / name, agent_registry=self.registry
        )

    def make_client(
        self,
        *,
        mode: str,
        claude_runner,
        codex_runner,
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

    def test_erp_scenario_runs_analysis_sequence_and_stops_at_gate(self) -> None:
        plan_text = json.dumps(
            _plan_payload(
                [
                    _step("s1", "oracle"),
                    _step("s2", "athena"),
                    _step("s3", "nikita"),
                    _step("s4", "trinity"),
                    _step(
                        "s5",
                        "neo",
                        phase="implementation",
                        requires_approval=True,
                        objective="implementar o ERP",
                    ),
                ]
            )
        )
        claude = RoutedCliRunner(
            {
                "MORPHEUS": plan_text,
                "ORACLE": "requisitos de compras levantados",
                "ATHENA": "arquitetura de microservicos definida",
                "NIKITA": "modelo de dados de compras definido",
                "TRINITY": "fluxo de aprovacao de compras desenhado",
                "NEO": "NUNCA DEVERIA SER CHAMADO NESTA FASE",
            }
        )
        codex_guard = AlwaysFailsCliRunner()
        task_manager = self._task_manager()
        with self.make_client(
            mode="claude",
            claude_runner=claude,
            codex_runner=codex_guard,
            task_manager=task_manager,
        ) as client:
            response = client.post(
                "/api/agents/morpheus/plan",
                json={"message": "Jarvis, vamos começar um projeto para criar um ERP de Compras."},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["status"], "waiting_approval")
            executed_agents = [s["agent_id"] for s in body["steps_executed"]]
            self.assertEqual(executed_agents, ["oracle", "athena", "nikita", "trinity"])
            self.assertEqual(body["consolidated"]["next_step"]["agent_id"], "neo")
            # codex_guard pode ter recebido a sonda de startup
            # (refresh_codex_provider, stdin_text=None); nenhuma chamada de
            # CHAT real (stdin_text preenchido) pode te-lo alcancado.
            chat_calls = [c for c in codex_guard.calls if c["stdin_text"]]
            self.assertEqual(chat_calls, [])

            agents = {
                a["id"]: a["status"]
                for a in client.get("/api/agents").json()["agents"]
            }
            self.assertEqual(agents["morpheus"], "waiting")
            self.assertEqual(agents["neo"], "idle")
            for agent_id in ("oracle", "athena", "nikita", "trinity"):
                self.assertEqual(agents[agent_id], "idle")
            for agent_id in ("hephaestus", "apollo"):
                self.assertEqual(agents[agent_id], "idle")

            tasks = client.get("/api/tasks").json()["tasks"]
            agent_ids_with_tasks = {t["agent_id"] for t in tasks}
            self.assertEqual(
                agent_ids_with_tasks,
                {"morpheus", "oracle", "athena", "nikita", "trinity"},
            )

        no_neo_call = all("NUNCA DEVERIA" not in str(c) for c in claude.calls[-1:])
        self.assertTrue(no_neo_call)

    def test_different_request_can_select_a_different_subset_of_specialists(
        self,
    ) -> None:
        # Prova que o sistema nao fixa "ERP sempre = 4 agentes": um pedido
        # diferente pode gerar um plano com um subconjunto distinto.
        plan_text = json.dumps(
            _plan_payload(
                objective="Investigar lentidao de uma consulta SQL",
                steps=[_step("s1", "nikita"), _step("s2", "apollo")],
            )
        )
        claude = RoutedCliRunner(
            {
                "MORPHEUS": plan_text,
                "NIKITA": "consulta otimizada",
                "APOLLO": "regressao validada",
            }
        )
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=AlwaysFailsCliRunner()
        ) as client:
            response = client.post(
                "/api/agents/morpheus/plan",
                json={"message": "Investigue a lentidao dessa consulta SQL"},
            )
            body = response.json()
            self.assertEqual(
                [s["agent_id"] for s in body["steps_executed"]], ["nikita", "apollo"]
            )

    def test_invalid_plan_returns_error_without_executing_specialists(self) -> None:
        claude = RoutedCliRunner({"MORPHEUS": "texto livre, nao e JSON"})
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=AlwaysFailsCliRunner()
        ) as client:
            response = client.post(
                "/api/agents/morpheus/plan", json={"message": "tarefa qualquer"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "error")

            agents = {
                a["id"]: a["status"]
                for a in client.get("/api/agents").json()["agents"]
            }
            self.assertEqual(agents["morpheus"], "error")

    def test_codex_mode_is_respected_for_morpheus_planning(self) -> None:
        plan_text = json.dumps(_plan_payload(steps=[_step("s1", "oracle")]))
        codex = RoutedCliRunner({"MORPHEUS": plan_text, "ORACLE": "ok"})
        with self.make_client(
            mode="codex", claude_runner=AlwaysFailsCliRunner(), codex_runner=codex
        ) as client:
            response = client.post(
                "/api/agents/morpheus/plan", json={"message": "tarefa"}
            )
            self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(codex.calls), 1)

    def test_explicit_specialist_endpoint_still_works_after_morpheus(self) -> None:
        claude = RoutedCliRunner({"ORACLE": "requisitos ok"})
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=AlwaysFailsCliRunner()
        ) as client:
            response = client.post(
                "/api/agents/oracle/run", json={"message": "levante os requisitos"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "completed")

    def test_plain_chat_still_works_after_morpheus_endpoint_exists(self) -> None:
        claude = RoutedCliRunner({"": "resposta normal do chat"})
        with self.make_client(
            mode="claude", claude_runner=claude, codex_runner=AlwaysFailsCliRunner()
        ) as client:
            response = client.post("/api/chat", json={"message": "oi jarvis"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "resposta normal do chat")

    def test_morpheus_run_via_generic_specialist_endpoint_is_still_rejected(
        self,
    ) -> None:
        with self.make_client(
            mode="claude",
            claude_runner=AlwaysFailsCliRunner(),
            codex_runner=AlwaysFailsCliRunner(),
        ) as client:
            response = client.post(
                "/api/agents/morpheus/run", json={"message": "tarefa"}
            )
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
