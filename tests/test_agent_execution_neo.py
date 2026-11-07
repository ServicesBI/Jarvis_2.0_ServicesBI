"""RED/GREEN da Fase 4A: contrato runtime operacional + execução de NEO.

Testes unitários, sem tocar CLI real de Claude/Codex: o AgentExecutionService é
exercitado com um ChatExecutor controlável, para provar status IDLE/WORKING/ERROR
e isolamento de outros agentes.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

from app.agents.execution import AgentExecutionService
from app.agents.models import AgentStatus
from app.agents.registry import UnknownAgentError, create_agent_registry
from app.agents.runtime import (
    AgentOperatingProfileNotFoundError,
    get_operating_profile,
)
from app.agents.state import AgentRuntimeStateService
from app.chat.executor import AvailabilityObservedExecutor, ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.executors.availability import ProviderAvailabilityService
from app.tasks.manager import TaskManager


class ControllableExecutor(ChatExecutor):
    """ChatExecutor cujo início e liberação são controlados pelo teste."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.chunks: list[str] = ["resultado real de NEO"]
        self.raise_error = False
        self.received_request: ChatRequest | None = None

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.received_request = request
        self.started.set()
        await self.release.wait()
        if self.raise_error:
            raise RuntimeError("falha simulada do provider")
        for chunk in self.chunks:
            yield chunk


async def _never_disconnected() -> bool:
    return False


class AgentRuntimeProfileTests(unittest.TestCase):
    def test_neo_has_operating_profile_with_matching_agent_id(self) -> None:
        profile = get_operating_profile("neo")
        self.assertEqual(profile.agent_id, "neo")
        self.assertTrue(profile.operating_prompt.strip())

    def test_agent_without_registered_profile_raises(self) -> None:
        with self.assertRaises(AgentOperatingProfileNotFoundError):
            get_operating_profile("morpheus")


class AgentExecutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()
        self.task_manager = TaskManager(
            Path(self.temp_dir.name) / "task-state.json",
            agent_registry=self.registry,
        )
        self.state = AgentRuntimeStateService()
        self.executor = ControllableExecutor()
        self.availability = ProviderAvailabilityService()
        self.observed_executor = AvailabilityObservedExecutor(
            "claude",
            self.executor,
            self.availability,
            task_manager=self.task_manager,
        )
        self.chat_service = ChatService(self.observed_executor)
        self.service = AgentExecutionService(
            self.chat_service,
            self.registry,
            self.state,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_no_markdown_is_read_during_execution(self) -> None:
        self.executor.release.set()
        with patch.object(
            Path,
            "read_text",
            side_effect=AssertionError("execução não deve ler Markdown"),
        ):
            result = asyncio.run(self.service.run("neo", "implemente algo simples"))
        self.assertEqual(result["status"], "completed")

    def test_operating_prompt_is_sent_to_the_executor(self) -> None:
        self.executor.release.set()
        asyncio.run(self.service.run("neo", "corrija o bug X"))
        received = self.executor.received_request
        assert received is not None
        self.assertIn("NEO", received.message)
        self.assertIn("corrija o bug X", received.message)
        self.assertEqual(received.agent_id, "neo")

    def test_unknown_agent_id_is_rejected(self) -> None:
        with self.assertRaises(UnknownAgentError):
            asyncio.run(self.service.run("dex", "tarefa"))

    def test_agent_without_operating_profile_is_rejected(self) -> None:
        # MORPHEUS é um agent_id canônico válido no AgentRegistry, mas
        # permanece deliberadamente sem contrato operacional executável
        # (Fase 4C não implementa MORPHEUS).
        with self.assertRaises(AgentOperatingProfileNotFoundError):
            asyncio.run(self.service.run("morpheus", "tarefa"))

    def test_success_returns_to_idle_and_task_completes(self) -> None:
        self.executor.release.set()
        result = asyncio.run(self.service.run("neo", "tarefa segura"))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)
        tasks = self.task_manager.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["agent_id"], "neo")
        self.assertEqual(tasks[0]["status"], "completed")

    def test_failure_moves_to_error_and_task_fails(self) -> None:
        self.executor.raise_error = True
        self.executor.release.set()
        result = asyncio.run(self.service.run("neo", "tarefa que falha"))

        self.assertEqual(result["status"], "error")
        self.assertEqual(self.state.get_status("neo"), AgentStatus.ERROR)
        tasks = self.task_manager.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "failed")

    def test_failure_never_reports_idle_or_completed(self) -> None:
        self.executor.raise_error = True
        self.executor.release.set()
        result = asyncio.run(self.service.run("neo", "tarefa que falha"))

        self.assertNotEqual(result["status"], "completed")
        self.assertNotEqual(self.state.get_status("neo"), AgentStatus.IDLE)

    def test_status_transitions_idle_to_working_during_real_execution(self) -> None:
        async def scenario() -> None:
            self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)
            run_task = asyncio.create_task(self.service.run("neo", "tarefa"))
            await self.executor.started.wait()

            self.assertEqual(self.state.get_status("neo"), AgentStatus.WORKING)

            self.executor.release.set()
            result = await run_task
            self.assertEqual(result["status"], "completed")
            self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)

        asyncio.run(scenario())

    def test_other_agents_stay_idle_while_neo_is_working(self) -> None:
        async def scenario() -> None:
            run_task = asyncio.create_task(self.service.run("neo", "tarefa"))
            await self.executor.started.wait()

            for agent_id in (
                "morpheus",
                "oracle",
                "nikita",
                "athena",
                "hephaestus",
                "apollo",
                "trinity",
            ):
                self.assertEqual(self.state.get_status(agent_id), AgentStatus.IDLE)

            self.executor.release.set()
            await run_task

            for agent_id in (
                "morpheus",
                "oracle",
                "nikita",
                "athena",
                "hephaestus",
                "apollo",
                "trinity",
            ):
                self.assertEqual(self.state.get_status(agent_id), AgentStatus.IDLE)

        asyncio.run(scenario())

    def test_new_execution_clears_previous_error(self) -> None:
        self.executor.raise_error = True
        self.executor.release.set()
        asyncio.run(self.service.run("neo", "falha"))
        self.assertEqual(self.state.get_status("neo"), AgentStatus.ERROR)

        self.executor.raise_error = False
        self.executor.release.set()
        result = asyncio.run(self.service.run("neo", "sucesso depois de falha"))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)

    def test_plain_chat_without_agent_id_keeps_working_and_stays_out_of_agent_state(
        self,
    ) -> None:
        self.executor.release.set()
        request = ChatRequest(message="pergunta comum sem agente")

        async def collect() -> str:
            return "".join(
                [
                    chunk
                    async for chunk in self.chat_service.stream(
                        request, _never_disconnected
                    )
                ]
            )

        content = asyncio.run(collect())
        self.assertEqual(content, "resultado real de NEO")
        self.assertIsNone(self.executor.received_request.agent_id)


if __name__ == "__main__":
    unittest.main()
