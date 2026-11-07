from __future__ import annotations

import asyncio
import importlib
import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.actions.engine import ActionEngine
from app.actions.models import ActionRequest, ActionRisk, PersistencePolicy
from app.actions.policy import ActionPolicy
from app.actions.registry import ActionRegistry, UnknownActionError
from app.chat.action_dispatcher import ActionDispatcher
from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.main import create_app
from app.tasks.manager import TaskManager


def _app_open_module():
    return importlib.import_module("app.actions.app_open")


class FakeChatExecutor(ChatExecutor):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        yield "provider should not run"


class RecordingPolicy(ActionPolicy):
    def __init__(self) -> None:
        self.requests: list[ActionRequest] = []

    def authorize(self, definition, request: ActionRequest) -> None:
        self.requests.append(request)
        super().authorize(definition, request)


class AppOpenSchemaAndDefinitionTests(unittest.TestCase):
    def test_schema_is_closed_and_accepts_only_allowlisted_applications(self) -> None:
        module = _app_open_module()
        for application in ("vscode", "word", "excel", "powerbi"):
            with self.subTest(application=application):
                self.assertEqual(
                    module.AppOpenInput.model_validate(
                        {"application": application}
                    ).application,
                    application,
                )
        for application in ("powershell", "cmd", "terminal", "bash", "pwsh", "regedit"):
            with self.subTest(application=application):
                with self.assertRaises(ValidationError):
                    module.AppOpenInput.model_validate({"application": application})
        for field in (
            "command",
            "executable",
            "path",
            "args",
            "arguments",
            "working_directory",
            "shell",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    module.AppOpenInput.model_validate(
                        {"application": "vscode", field: "forbidden"}
                    )

    def test_definition_uses_desktop_contract_and_verifier(self) -> None:
        module = _app_open_module()
        definition = module.create_app_open_definition()
        self.assertEqual(definition.name, "app.open")
        self.assertEqual(definition.risk, ActionRisk.DESKTOP)
        self.assertFalse(definition.confirmation_required)
        self.assertEqual(definition.allowed_sources, frozenset({"chat", "api"}))
        self.assertTrue(definition.desktop_exclusive)
        self.assertTrue(definition.requires_verification)
        self.assertIsNotNone(definition.verifier)
        self.assertEqual(definition.persistence, PersistencePolicy.SANITIZED)


class AppOpenResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def executable(self, name: str) -> Path:
        path = self.root / name
        path.write_bytes(b"MZ")
        return path

    def test_registry_is_preferred_and_only_expected_executable_is_accepted(self) -> None:
        module = _app_open_module()
        code = self.executable("Code.exe")
        fallback = self.executable("fallback-Code.exe")
        result = module.resolve_application(
            "vscode",
            registry_lookup=lambda _name: code,
            known_paths=lambda _app: (fallback,),
            which=lambda _name: None,
            trusted_roots=lambda _app: (self.root,),
        )
        self.assertEqual(result.executable, code.resolve())
        self.assertEqual(result.method, "registry_app_paths")

    def test_wrong_registry_basename_is_rejected_before_safe_fallback(self) -> None:
        module = _app_open_module()
        wrong = self.executable("powershell.exe")
        safe = self.executable("WINWORD.EXE")
        result = module.resolve_application(
            "word",
            registry_lookup=lambda _name: wrong,
            known_paths=lambda _app: (safe,),
            which=lambda _name: None,
            trusted_roots=lambda _app: (self.root,),
        )
        self.assertEqual(result.executable, safe.resolve())
        self.assertEqual(result.method, "known_path")

    def test_expected_basename_outside_trusted_roots_is_rejected(self) -> None:
        module = _app_open_module()
        trusted_root = self.root / "trusted"
        trusted_root.mkdir()
        safe = trusted_root / "Code.exe"
        safe.write_bytes(b"MZ")
        untrusted_root = self.root / "untrusted"
        untrusted_root.mkdir()
        homonym = untrusted_root / "Code.exe"
        homonym.write_bytes(b"MZ")

        result = module.resolve_application(
            "vscode",
            registry_lookup=lambda _name: homonym,
            known_paths=lambda _app: (safe,),
            which=lambda _name: str(homonym),
            trusted_roots=lambda _app: (trusted_root,),
        )

        self.assertEqual(result.executable, safe.resolve())
        self.assertEqual(result.method, "known_path")

    def test_which_must_resolve_the_expected_exe_not_a_cmd_wrapper(self) -> None:
        module = _app_open_module()
        wrapper = self.executable("code.cmd")
        with self.assertRaises(FileNotFoundError):
            module.resolve_application(
                "vscode",
                registry_lookup=lambda _name: None,
                known_paths=lambda _app: (),
                which=lambda _name: str(wrapper),
            )

    def test_missing_executable_fails_without_fallback_side_effect(self) -> None:
        module = _app_open_module()
        with self.assertRaises(FileNotFoundError):
            module.resolve_application(
                "powerbi",
                registry_lookup=lambda _name: None,
                known_paths=lambda _app: (),
                which=lambda _name: None,
            )

    def test_launcher_uses_one_structured_argument_and_shell_false(self) -> None:
        module = _app_open_module()
        executable = self.executable("EXCEL.EXE")
        with patch("app.actions.app_open.subprocess.Popen") as popen:
            module.launch_application(executable)
        popen.assert_called_once_with(
            [str(executable.resolve())],
            shell=False,
            close_fds=True,
        )


class AppOpenEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.manager = TaskManager(self.root / "task-state.json")

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.temp_dir.cleanup()

    async def _execute(self, *, before: set[int], after: set[int]):
        module = _app_open_module()
        executable = self.root / "Code.exe"
        executable.write_bytes(b"MZ")
        snapshots = [before, after]
        launches: list[tuple[list[str], bool]] = []

        def resolver(application: str):
            return module.ExecutableResolution(
                application=application,
                executable=executable.resolve(),
                method="test",
            )

        def snapshot(_resolution):
            return set(snapshots.pop(0)) if snapshots else set(after)

        def launcher(path: Path):
            launches.append(([str(path)], False))

        policy = RecordingPolicy()
        registry = ActionRegistry()
        registry.register(
            module.create_app_open_definition(
                resolver=resolver,
                launcher=launcher,
                process_snapshot=snapshot,
                verification_attempts=1,
                verification_delay=0,
            )
        )
        engine = ActionEngine(registry, self.manager, policy)
        request = ActionRequest(
            action="app.open",
            arguments={"application": "vscode"},
            source="chat",
        )
        submitted = engine.submit(request)
        finished = await self.manager.wait(submitted["task_id"])
        return finished, launches, policy

    async def test_action_engine_launches_structured_executable_and_verifies_process(self) -> None:
        finished, launches, policy = await self._execute(before=set(), after={41})
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["type"], "app.open")
        self.assertEqual(len(launches), 1)
        self.assertEqual(Path(launches[0][0][0]).name, "Code.exe")
        self.assertFalse(launches[0][1])
        self.assertEqual(len(policy.requests), 1)
        self.assertEqual(finished["result"]["data"], {
            "application": "vscode",
            "launched": True,
            "process_detected": True,
            "process_preexisting": False,
            "executable_name": "Code.exe",
        })
        self.assertNotIn(str(self.root), json.dumps(finished["result"]))

    async def test_existing_process_is_valid_verification(self) -> None:
        finished, _, _ = await self._execute(before={41}, after={41})
        self.assertEqual(finished["status"], "completed")
        self.assertTrue(finished["result"]["data"]["process_preexisting"])
        self.assertTrue(finished["result"]["data"]["process_detected"])

    async def test_task_fails_when_expected_process_never_appears(self) -> None:
        finished, _, _ = await self._execute(before=set(), after=set())
        self.assertEqual(finished["status"], "failed")
        self.assertIsNone(finished["result"])
        self.assertIn("Verifier", finished["error"])

    async def test_unknown_action_before_registration_is_rejected(self) -> None:
        engine = ActionEngine(ActionRegistry(), self.manager)
        with self.assertRaises(UnknownActionError):
            engine.submit(
                ActionRequest(
                    action="app.open",
                    arguments={"application": "vscode"},
                    source="chat",
                )
            )


class AppOpenDispatcherTests(unittest.TestCase):
    def test_explicit_commands_resolve_to_app_open_with_chat_source(self) -> None:
        cases = {
            "Abra o VS Code.": "vscode",
            "Jarvis, abra o Word.": "word",
            "Inicie o Excel.": "excel",
            "Abra o Power BI.": "powerbi",
        }
        dispatcher = ActionDispatcher()
        for message, application in cases.items():
            with self.subTest(message=message):
                request = dispatcher.resolve(message)
                self.assertIsInstance(request, ActionRequest)
                self.assertEqual(request.action, "app.open")
                self.assertEqual(request.arguments, {"application": application})
                self.assertEqual(request.source, "chat")

    def test_questions_explanations_targets_and_ambiguity_do_not_resolve(self) -> None:
        messages = (
            "O que é VS Code?",
            "Você consegue abrir o Excel?",
            "Como abrir o Word?",
            "Explique como iniciar o Power BI.",
            "Qual a diferença entre Excel e Word?",
            "Abra Relatorio.docx no Word.",
            "Abra Analise.xlsx no Excel.",
            "Abra Analise Financeira.pbix no Power BI.",
            "Abra a pasta Documents and Projects no VS Code.",
            "Abra Word e Excel.",
            "Abra o PowerShell.",
            "Abra o cmd.",
        )
        dispatcher = ActionDispatcher()
        for message in messages:
            with self.subTest(message=message):
                self.assertIsNone(dispatcher.resolve(message))


class AppOpenChatIntegrationTests(unittest.TestCase):
    def test_chat_uses_action_engine_without_calling_provider(self) -> None:
        module = _app_open_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = root / "Code.exe"
            executable.write_bytes(b"MZ")
            resolution = module.ExecutableResolution(
                application="vscode",
                executable=executable.resolve(),
                method="test",
            )
            fake_chat = FakeChatExecutor()
            with (
                patch("app.actions.app_open.resolve_application", return_value=resolution),
                patch("app.actions.app_open.launch_application"),
                patch("app.actions.app_open.process_ids_for", side_effect=[set(), {91}]),
            ):
                client = TestClient(create_app(ChatService(fake_chat)))
                try:
                    response = client.post(
                        "/api/chat",
                        json={"message": "Jarvis, abra o VS Code."},
                    )
                finally:
                    client.close()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Tarefa registrada", response.text)
        self.assertIn("concluida com efeito real", response.text)
        self.assertNotIn("[error]", response.text)
        self.assertEqual(fake_chat.requests, [])

    def test_word_and_excel_creation_dispatch_remains_independent(self) -> None:
        dispatcher = ActionDispatcher()
        word = dispatcher.resolve(
            "Crie um Word chamado Relatorio.docx com o texto: Conteudo"
        )
        excel = dispatcher.resolve(
            "Crie uma planilha chamada Dados.xlsx com os dados: "
            "cabecalhos: Nome, Valor; linhas: A, 1"
        )
        self.assertEqual(word.action, "word.create")
        self.assertEqual(excel.action, "excel.create")


if __name__ == "__main__":
    unittest.main()
