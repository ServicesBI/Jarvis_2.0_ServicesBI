from __future__ import annotations

import tempfile
import unittest
from collections.abc import AsyncIterator
from dataclasses import fields
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.actions.engine import ActionEngine
from app.actions.models import ActionRequest, ActionResult, ActionRisk, PersistencePolicy
from app.actions.registry import ActionDefinition, ActionRegistry
from app.chat.action_dispatcher import ActionDispatcher
from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.main import create_app
from app.tasks.manager import TaskManager


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class OpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class RecordingChatExecutor(ChatExecutor):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        yield "provider fallback"


class FileOpenIntentTests(unittest.TestCase):
    def test_known_applications_keep_app_open_priority(self) -> None:
        cases = {
            "Abra o Word": "word",
            "Abra o Excel": "excel",
            "Abra o Power BI": "powerbi",
            "Abra o VS Code": "vscode",
        }
        dispatcher = ActionDispatcher()

        for message, application in cases.items():
            with self.subTest(message=message):
                resolution = dispatcher.resolve(message)
                self.assertIsInstance(resolution, ActionRequest)
                self.assertEqual(resolution.action, "app.open")
                self.assertEqual(resolution.arguments, {"application": application})

    def test_explicit_file_commands_preserve_only_the_literal_name(self) -> None:
        cases = {
            "Abra o arquivo Planilha Jarvis": "Planilha Jarvis",
            "Abra o documento Proposta": "Proposta",
            "Abra o arquivo Planilha Jarvis.xlsx": "Planilha Jarvis.xlsx",
        }
        dispatcher = ActionDispatcher()

        for message, expected_name in cases.items():
            with self.subTest(message=message):
                resolution = dispatcher.resolve(message)
                self.assertEqual(type(resolution).__name__, "FileOpenIntent")
                self.assertEqual(
                    {field.name: getattr(resolution, field.name) for field in fields(resolution)},
                    {"name": expected_name},
                )

    def test_supported_extension_is_a_bounded_implicit_file_signal(self) -> None:
        dispatcher = ActionDispatcher()

        resolution = dispatcher.resolve("Abra Planilha Jarvis.xlsx")

        self.assertEqual(type(resolution).__name__, "FileOpenIntent")
        self.assertEqual(
            {field.name: getattr(resolution, field.name) for field in fields(resolution)},
            {"name": "Planilha Jarvis.xlsx"},
        )

    def test_broad_open_requests_do_not_become_file_intents(self) -> None:
        messages = (
            "Abra as configuracoes do sistema",
            "Abra uma nova planilha",
            "Abra meu painel financeiro",
            "Abra o navegador agora",
            "Abra a Planilha Jarvis",
        )
        dispatcher = ActionDispatcher()

        for message in messages:
            with self.subTest(message=message):
                self.assertIsNone(dispatcher.resolve(message))


class FileOpenChatIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = TaskManager(Path(self.temp_dir.name) / "task-state.json")
        self.chat_executor = RecordingChatExecutor()
        self.resolve_outcome: ActionResult | Exception = ActionResult(
            ok=True,
            action="file.resolve",
            summary="Arquivo resolvido.",
            data={
                "status": "found",
                "filename": "Planilha Jarvis.xlsx",
                "path": "Planilha Jarvis.xlsx",
                "extension": ".xlsx",
                "candidates": [],
            },
        )
        self.open_outcome: ActionResult | Exception = ActionResult(
            ok=True,
            action="file.open",
            summary="Arquivo aberto.",
            data={
                "application": "excel",
                "file": "Planilha Jarvis.xlsx",
                "process_detected": True,
            },
        )
        self.executed: list[tuple[str, dict[str, str]]] = []

        async def resolve_handler(arguments: ResolveInput) -> ActionResult:
            self.executed.append(("file.resolve", arguments.model_dump()))
            if isinstance(self.resolve_outcome, Exception):
                raise self.resolve_outcome
            return self.resolve_outcome

        async def open_handler(arguments: OpenInput) -> ActionResult:
            self.executed.append(("file.open", arguments.model_dump()))
            if isinstance(self.open_outcome, Exception):
                raise self.open_outcome
            return self.open_outcome

        async def verify(_arguments: BaseModel, _result: ActionResult) -> bool:
            return True

        registry = ActionRegistry()
        registry.register(
            ActionDefinition(
                name="file.resolve",
                description="Resolve arquivo controlado.",
                input_model=ResolveInput,
                handler=resolve_handler,
                verifier=verify,
                risk=ActionRisk.READ,
                confirmation_required=False,
                timeout=2.0,
                desktop_exclusive=False,
                persistence=PersistencePolicy.SANITIZED,
                allowed_sources=frozenset({"chat"}),
            )
        )
        registry.register(
            ActionDefinition(
                name="file.open",
                description="Abre arquivo controlado.",
                input_model=OpenInput,
                handler=open_handler,
                verifier=verify,
                risk=ActionRisk.DESKTOP,
                confirmation_required=False,
                timeout=2.0,
                desktop_exclusive=True,
                persistence=PersistencePolicy.SANITIZED,
                allowed_sources=frozenset({"chat"}),
            )
        )
        application = create_app(
            ChatService(self.chat_executor), task_manager=self.manager
        )
        application.state.action_engine = ActionEngine(registry, self.manager)
        self.client = TestClient(application)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def post(self, message: str = "Abra o arquivo Planilha Jarvis"):
        return self.client.post("/api/chat", json={"message": message})

    def test_found_submits_two_independent_actions_with_exact_resolved_path(self) -> None:
        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.executed,
            [
                ("file.resolve", {"name": "Planilha Jarvis"}),
                ("file.open", {"path": "Planilha Jarvis.xlsx"}),
            ],
        )
        tasks = list(reversed(self.manager.list()))
        self.assertEqual([task["type"] for task in tasks], ["file.resolve", "file.open"])
        self.assertEqual([task["status"] for task in tasks], ["completed", "completed"])
        self.assertIn("Abri Planilha Jarvis.xlsx no Excel.", response.text)
        self.assertEqual(self.chat_executor.requests, [])

    def test_not_found_stops_after_resolve_without_fallback(self) -> None:
        self.resolve_outcome = ActionResult(
            ok=True,
            action="file.resolve",
            data={"status": "not_found", "candidates": []},
        )

        response = self.post("Abra o documento Ausente")

        self.assertEqual(self.executed, [("file.resolve", {"name": "Ausente"})])
        self.assertIn('Nao encontrei "Ausente" em Documents and Projects.', response.text)
        self.assertEqual(self.chat_executor.requests, [])

    def test_ambiguous_preserves_candidates_and_never_opens_one(self) -> None:
        self.resolve_outcome = ActionResult(
            ok=True,
            action="file.resolve",
            data={
                "status": "ambiguous",
                "candidates": ["Analise.pbix", "Analise.xlsx"],
            },
        )

        response = self.post("Abra o arquivo Analise")

        self.assertEqual(self.executed, [("file.resolve", {"name": "Analise"})])
        self.assertLess(response.text.index("Analise.pbix"), response.text.index("Analise.xlsx"))
        self.assertIn("Informe qual deles voce quer abrir.", response.text)
        self.assertEqual(self.chat_executor.requests, [])

    def test_resolve_technical_failure_is_sanitized_and_does_not_open(self) -> None:
        self.resolve_outcome = RuntimeError(
            r"Falha interna em C:\Users\Usuario\Documents and Projects"
        )

        response = self.post()

        self.assertEqual(self.executed, [("file.resolve", {"name": "Planilha Jarvis"})])
        self.assertIn("Falha tecnica ao resolver o arquivo.", response.text)
        self.assertNotIn("C:\\Users", response.text)
        self.assertNotIn("Nao encontrei", response.text)

    def test_open_technical_failure_is_sanitized_without_false_success(self) -> None:
        self.open_outcome = RuntimeError(r"Falha interna em C:\Program Files\Excel")

        response = self.post()

        self.assertEqual(
            self.executed,
            [
                ("file.resolve", {"name": "Planilha Jarvis"}),
                ("file.open", {"path": "Planilha Jarvis.xlsx"}),
            ],
        )
        self.assertIn("Encontrei o arquivo, mas nao consegui abri-lo.", response.text)
        self.assertNotIn("C:\\Program Files", response.text)
        self.assertNotIn("Abri Planilha", response.text)


if __name__ == "__main__":
    unittest.main()
