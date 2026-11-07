"""RED/GREEN da Fase 5A: sequenciamento, handoff, gate e falhas de MORPHEUS.

Unit-level: um ScriptedExecutor decide a resposta por agent_id (a mesma
cadeia AvailabilityObservedExecutor -> ChatService usada em produção), sem
tocar CLI real de Claude/Codex.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

from app.agents.execution import AgentExecutionService
from app.agents.models import AgentStatus
from app.agents.registry import create_agent_registry
from app.agents.orchestration import MorpheusOrchestrationService
from app.agents.state import AgentRuntimeStateService
from app.chat.executor import AvailabilityObservedExecutor, ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.executors.availability import ProviderAvailabilityService
from app.tasks.manager import TaskManager


def _plan_json(steps: list[dict], **overrides) -> str:
    payload = {
        "objective": "Criar um ERP de Compras",
        "summary": "Analise inicial antes da implementacao",
        "steps": steps,
        "requires_approval_before_execution": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


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


class ScriptedExecutor(ChatExecutor):
    """Responde de forma diferente por agent_id, como um provider real faria."""

    def __init__(self, responses: dict[str, str | BaseException]) -> None:
        self._responses = responses
        self.calls: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        response = self._responses[request.agent_id]
        if isinstance(response, BaseException):
            raise response
        yield response


class MorpheusOrchestrationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()
        self.task_manager = TaskManager(
            Path(self.temp_dir.name) / "task-state.json",
            agent_registry=self.registry,
        )
        self.state = AgentRuntimeStateService()
        self.availability = ProviderAvailabilityService()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_service(
        self, responses: dict[str, str | BaseException]
    ) -> tuple[MorpheusOrchestrationService, ScriptedExecutor]:
        scripted = ScriptedExecutor(responses)
        observed = AvailabilityObservedExecutor(
            "claude", scripted, self.availability, task_manager=self.task_manager
        )
        chat_service = ChatService(observed)
        execution_service = AgentExecutionService(chat_service, self.registry, self.state)
        return (
            MorpheusOrchestrationService(execution_service, self.state),
            scripted,
        )

    def test_sequential_order_oracle_before_athena(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle"), _step("s2", "athena")])
        service, scripted = self._build_service(
            {
                "morpheus": plan_text,
                "oracle": "requisitos levantados",
                "athena": "arquitetura definida",
            }
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        agent_call_order = [call.agent_id for call in scripted.calls]
        self.assertEqual(agent_call_order, ["morpheus", "oracle", "athena"])
        self.assertEqual(result["status"], "waiting_approval")
        self.assertEqual(
            [s["agent_id"] for s in result["steps_executed"]], ["oracle", "athena"]
        )

    def test_athena_receives_oracle_output_as_handoff(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle"), _step("s2", "athena")])
        service, scripted = self._build_service(
            {
                "morpheus": plan_text,
                "oracle": "REQUISITO-CHAVE: modulo de compras com aprovacao",
                "athena": "arquitetura ok",
            }
        )
        asyncio.run(service.plan("Criar um ERP de Compras"))

        athena_call = next(call for call in scripted.calls if call.agent_id == "athena")
        self.assertIn("REQUISITO-CHAVE", athena_call.message)

    def test_nikita_receives_labeled_context_not_raw_dump(self) -> None:
        plan_text = _plan_json(
            [_step("s1", "oracle"), _step("s2", "athena"), _step("s3", "nikita")]
        )
        service, scripted = self._build_service(
            {
                "morpheus": plan_text,
                "oracle": "requisitos de dados",
                "athena": "arquitetura de dados",
                "nikita": "modelo definido",
            }
        )
        asyncio.run(service.plan("Criar um ERP de Compras"))

        nikita_call = next(call for call in scripted.calls if call.agent_id == "nikita")
        self.assertIn("oracle:", nikita_call.message)
        self.assertIn("athena:", nikita_call.message)
        self.assertIn("Objetivo global", nikita_call.message)

    def test_trinity_can_execute_as_analysis_step(self) -> None:
        plan_text = _plan_json([_step("s1", "trinity")])
        service, scripted = self._build_service(
            {"morpheus": plan_text, "trinity": "fluxo de UX definido"}
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        self.assertEqual(result["steps_executed"][0]["agent_id"], "trinity")
        self.assertEqual(result["steps_executed"][0]["status"], "completed")

    def test_gate_stops_before_neo_implementation(self) -> None:
        plan_text = _plan_json(
            [
                _step("s1", "oracle"),
                _step(
                    "s2",
                    "neo",
                    phase="implementation",
                    requires_approval=True,
                    objective="implementar o ERP",
                ),
            ]
        )
        service, scripted = self._build_service(
            {
                "morpheus": plan_text,
                "oracle": "requisitos ok",
                "neo": "NUNCA DEVERIA SER CHAMADO",
            }
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        called_agents = [call.agent_id for call in scripted.calls]
        self.assertNotIn("neo", called_agents)
        self.assertEqual(result["status"], "waiting_approval")
        self.assertEqual(result["consolidated"]["next_step"]["agent_id"], "neo")
        self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)

    def test_morpheus_status_reaches_waiting_at_the_gate(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle")])
        service, _scripted = self._build_service(
            {"morpheus": plan_text, "oracle": "ok"}
        )
        self.assertEqual(self.state.get_status("morpheus"), AgentStatus.IDLE)
        asyncio.run(service.plan("Criar um ERP de Compras"))
        self.assertEqual(self.state.get_status("morpheus"), AgentStatus.WAITING)

    def test_only_executed_specialists_change_and_all_return_to_idle(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle"), _step("s2", "athena")])
        service, _scripted = self._build_service(
            {"morpheus": plan_text, "oracle": "ok", "athena": "ok"}
        )
        asyncio.run(service.plan("Criar um ERP de Compras"))

        self.assertEqual(self.state.get_status("oracle"), AgentStatus.IDLE)
        self.assertEqual(self.state.get_status("athena"), AgentStatus.IDLE)
        for agent_id in ("nikita", "neo", "hephaestus", "apollo", "trinity"):
            self.assertEqual(self.state.get_status(agent_id), AgentStatus.IDLE)

    def test_specialist_failure_stops_the_sequence(self) -> None:
        plan_text = _plan_json(
            [_step("s1", "oracle"), _step("s2", "athena"), _step("s3", "nikita")]
        )
        service, scripted = self._build_service(
            {
                "morpheus": plan_text,
                "oracle": "ok",
                "athena": RuntimeError("falha simulada em athena"),
                "nikita": "NUNCA DEVERIA SER CHAMADO",
            }
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        called_agents = [call.agent_id for call in scripted.calls]
        self.assertNotIn("nikita", called_agents)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.state.get_status("athena"), AgentStatus.ERROR)
        self.assertEqual(self.state.get_status("morpheus"), AgentStatus.ERROR)

    def test_failure_never_reports_waiting_approval_or_success(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle")])
        service, _scripted = self._build_service(
            {"morpheus": plan_text, "oracle": RuntimeError("boom")}
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        self.assertEqual(result["status"], "error")
        self.assertNotEqual(result["status"], "waiting_approval")
        self.assertFalse(result["consolidated"]["waiting_approval"])

    def test_invalid_plan_json_prevents_any_specialist_execution(self) -> None:
        service, scripted = self._build_service(
            {"morpheus": "isto nao e JSON valido de plano"}
        )
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(len(scripted.calls), 1)  # somente a chamada de morpheus
        self.assertEqual(self.state.get_status("morpheus"), AgentStatus.ERROR)

    def test_plan_with_zeus_step_prevents_execution(self) -> None:
        plan_text = _plan_json([_step("s1", "zeus")])
        service, scripted = self._build_service({"morpheus": plan_text})
        result = asyncio.run(service.plan("Criar um ERP de Compras"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(len(scripted.calls), 1)

    def test_morpheus_task_has_its_own_agent_id(self) -> None:
        plan_text = _plan_json([_step("s1", "oracle")])
        service, _scripted = self._build_service(
            {"morpheus": plan_text, "oracle": "ok"}
        )
        asyncio.run(service.plan("Criar um ERP de Compras"))

        morpheus_tasks = [
            task
            for task in self.task_manager.list()
            if task["agent_id"] == "morpheus"
        ]
        self.assertEqual(len(morpheus_tasks), 1)
        self.assertEqual(morpheus_tasks[0]["type"], "chat.provider")


if __name__ == "__main__":
    unittest.main()
