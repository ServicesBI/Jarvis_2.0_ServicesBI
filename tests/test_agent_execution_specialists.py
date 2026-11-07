"""RED/GREEN da Fase 4C: generalizacao do runtime executavel para os 7
especialistas tecnicos do Jarvis (MORPHEUS continua fora).

Unit-level, sem CLI real: reaproveita o mesmo ControllableExecutor +
AvailabilityObservedExecutor de tests/test_agent_execution_neo.py, para
provar isolamento e concorrencia entre agentes distintos.
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


EXECUTABLE_AGENT_IDS = (
    "oracle",
    "nikita",
    "athena",
    "neo",
    "hephaestus",
    "apollo",
    "trinity",
)

NON_EXECUTABLE_IDS = ("morpheus", "zeus", "conclave", "dex", "orion", "foo")


class ControllableExecutor(ChatExecutor):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.chunks: list[str] = ["ok"]
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


class OperatingProfileCatalogTests(unittest.TestCase):
    def test_exactly_seven_agents_are_executable(self) -> None:
        for agent_id in EXECUTABLE_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                profile = get_operating_profile(agent_id)
                self.assertEqual(profile.agent_id, agent_id)
                self.assertTrue(profile.operating_prompt.strip())

    def test_morpheus_and_illegitimate_ids_have_no_operating_profile(self) -> None:
        for agent_id in NON_EXECUTABLE_IDS:
            with self.subTest(agent_id=agent_id):
                with self.assertRaises(AgentOperatingProfileNotFoundError):
                    get_operating_profile(agent_id)

    def test_each_agent_receives_its_own_distinct_prompt(self) -> None:
        prompts = {
            agent_id: get_operating_profile(agent_id).operating_prompt
            for agent_id in EXECUTABLE_AGENT_IDS
        }
        self.assertEqual(len(set(prompts.values())), len(EXECUTABLE_AGENT_IDS))
        for agent_id, prompt in prompts.items():
            with self.subTest(agent_id=agent_id):
                self.assertIn(agent_id.upper(), prompt)

    def test_hephaestus_prompt_grants_no_automatic_authorization(self) -> None:
        prompt = get_operating_profile("hephaestus").operating_prompt
        for required in (
            "nunca assumir autorização de push",
            "nunca assumir autorização de merge",
            "nunca assumir autorização de deploy",
            "nunca assumir autorização de rollback",
            "secrets",
            "ActionPolicy",
            "PathPolicy",
        ):
            with self.subTest(required=required):
                self.assertIn(required, prompt)


class AgentExecutionServiceSpecialistsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = create_agent_registry()
        self.task_manager = TaskManager(
            Path(self.temp_dir.name) / "task-state.json",
            agent_registry=self.registry,
        )
        self.state = AgentRuntimeStateService()
        self.availability = ProviderAvailabilityService()
        self.service = self._build_service()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_service(self) -> tuple[AgentExecutionService, ControllableExecutor]:
        executor = ControllableExecutor()
        observed = AvailabilityObservedExecutor(
            "claude", executor, self.availability, task_manager=self.task_manager
        )
        chat_service = ChatService(observed)
        service = AgentExecutionService(chat_service, self.registry, self.state)
        return service, executor

    def test_each_specialist_produces_a_task_with_matching_agent_id(self) -> None:
        for agent_id in EXECUTABLE_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                service, executor = self._build_service()
                executor.release.set()
                result = asyncio.run(service.run(agent_id, "tarefa segura"))

                self.assertEqual(result["status"], "completed")
                self.assertEqual(self.state.get_status(agent_id), AgentStatus.IDLE)
                tasks = [
                    task
                    for task in self.task_manager.list()
                    if task["agent_id"] == agent_id
                ]
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["status"], "completed")

    def test_each_specialist_can_fail_into_error(self) -> None:
        for agent_id in EXECUTABLE_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                service, executor = self._build_service()
                executor.raise_error = True
                executor.release.set()
                result = asyncio.run(service.run(agent_id, "tarefa que falha"))

                self.assertEqual(result["status"], "error")
                self.assertEqual(self.state.get_status(agent_id), AgentStatus.ERROR)

    def test_no_markdown_is_read_for_any_specialist(self) -> None:
        for agent_id in EXECUTABLE_AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                service, executor = self._build_service()
                executor.release.set()
                with patch.object(
                    Path,
                    "read_text",
                    side_effect=AssertionError("não deve ler Markdown"),
                ):
                    result = asyncio.run(service.run(agent_id, "tarefa"))
                self.assertEqual(result["status"], "completed")

    def test_morpheus_and_legacy_ids_are_rejected_by_the_service(self) -> None:
        service, _executor = self._build_service()
        with self.assertRaises(AgentOperatingProfileNotFoundError):
            asyncio.run(service.run("morpheus", "tarefa"))
        for agent_id in ("zeus", "conclave", "dex"):
            with self.subTest(agent_id=agent_id):
                with self.assertRaises(UnknownAgentError):
                    asyncio.run(service.run(agent_id, "tarefa"))

    def test_running_oracle_does_not_change_other_agents(self) -> None:
        service, executor = self._build_service()
        executor.release.set()
        asyncio.run(service.run("oracle", "tarefa"))

        self.assertEqual(self.state.get_status("oracle"), AgentStatus.IDLE)
        for agent_id in ("nikita", "athena", "neo", "hephaestus", "apollo", "trinity"):
            with self.subTest(agent_id=agent_id):
                self.assertEqual(self.state.get_status(agent_id), AgentStatus.IDLE)

    def test_two_specialists_can_be_working_independently_at_the_same_time(
        self,
    ) -> None:
        async def scenario() -> None:
            service_a, executor_a = self._build_service()
            service_b, executor_b = self._build_service()

            task_oracle = asyncio.create_task(service_a.run("oracle", "tarefa A"))
            task_athena = asyncio.create_task(service_b.run("athena", "tarefa B"))

            await executor_a.started.wait()
            await executor_b.started.wait()

            self.assertEqual(self.state.get_status("oracle"), AgentStatus.WORKING)
            self.assertEqual(self.state.get_status("athena"), AgentStatus.WORKING)
            self.assertEqual(self.state.get_status("neo"), AgentStatus.IDLE)

            executor_a.release.set()
            executor_b.release.set()
            result_oracle, result_athena = await asyncio.gather(
                task_oracle, task_athena
            )

            self.assertEqual(result_oracle["status"], "completed")
            self.assertEqual(result_athena["status"], "completed")
            self.assertEqual(self.state.get_status("oracle"), AgentStatus.IDLE)
            self.assertEqual(self.state.get_status("athena"), AgentStatus.IDLE)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
