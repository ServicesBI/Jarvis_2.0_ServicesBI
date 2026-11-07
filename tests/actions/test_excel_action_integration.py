from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError

from app.actions.engine import ActionEngine
from app.actions.excel import (
    XLSX_MEDIA_TYPE,
    ExcelCreateInput,
    create_excel_definition,
)
from app.actions.models import ActionArtifact, ActionRequest, ActionResult
from app.actions.policy import PathPolicy
from app.actions.registry import ActionRegistry
from app.chat.action_dispatcher import ActionDispatcher
from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.main import create_app
from app.tasks.manager import TaskManager
import app.actions.excel as excel_action_module
import app.automation.excel as excel_automation_module
import app.core.config as config_module


class RecordingChatExecutor(ChatExecutor):
    def __init__(self, response: str = "CHAT_FAKE") -> None:
        self.response = response
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest):
        self.requests.append(request)
        yield self.response


class ExcelWorkspaceDefaultTests(unittest.TestCase):
    def test_workspace_override_confines_default_to_excel_subroot(self) -> None:
        filename = "TDD Excel Workspace Root Migration.xlsx"
        original_environment = os.environ.get("JARVIS_WORKSPACE_ROOT")
        old_path = (
            config_module.PROJECT_ROOT / "Documents and Projects" / filename
        ).resolve()
        self.assertFalse(old_path.exists(), "O fixture exclusivo ja existe na root antiga")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "Workspace Override"
            expected_root = (workspace_root / "Excel").resolve()

            try:
                os.environ["JARVIS_WORKSPACE_ROOT"] = str(workspace_root)
                importlib.reload(config_module)
                importlib.reload(excel_automation_module)
                importlib.reload(excel_action_module)
                real_path_policy = excel_automation_module.PathPolicy

                class RecordingPathPolicy(real_path_policy):
                    instances: list["RecordingPathPolicy"] = []

                    def __init__(self, **kwargs):
                        super().__init__(**kwargs)
                        self.instances.append(self)

                async def execute():
                    with (
                        patch.object(
                            excel_automation_module,
                            "PathPolicy",
                            RecordingPathPolicy,
                        ),
                        patch.object(
                            excel_action_module,
                            "PathPolicy",
                            RecordingPathPolicy,
                        ),
                    ):
                        definition = excel_action_module.create_excel_definition()
                        payload = excel_action_module.ExcelCreateInput(
                            filename=filename,
                            headers=["Item", "Valor"],
                            rows=[["Teste", 1]],
                            sheet="Smoke",
                            openFile=False,
                        )
                        result = await definition.handler(payload)
                        verified = await definition.verifier(payload, result)
                    return result, verified

                result, verified = asyncio.run(execute())
                created = Path(result.artifacts[0].path).resolve()

                self.assertTrue(verified)
                self.assertEqual(config_module.EXCEL_WORKSPACE, expected_root)
                self.assertEqual(created, expected_root / filename)
                self.assertTrue(created.is_file())
                self.assertFalse((workspace_root / filename).exists())
                self.assertFalse(old_path.exists())
                self.assertGreaterEqual(len(RecordingPathPolicy.instances), 1)
                self.assertTrue(
                    all(
                        policy.write_roots == (expected_root,)
                        for policy in RecordingPathPolicy.instances
                    )
                )
            finally:
                if old_path.is_file():
                    old_path.unlink()
                if original_environment is None:
                    os.environ.pop("JARVIS_WORKSPACE_ROOT", None)
                else:
                    os.environ["JARVIS_WORKSPACE_ROOT"] = original_environment
                importlib.reload(config_module)
                importlib.reload(excel_automation_module)
                importlib.reload(excel_action_module)

        self.assertEqual(
            os.environ.get("JARVIS_WORKSPACE_ROOT"), original_environment
        )
        self.assertEqual(
            excel_automation_module.PROJECTS_DIR,
            config_module.EXCEL_WORKSPACE.resolve(),
        )


class ExcelActionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_dir = self.root / "output"
        self.manager = TaskManager(self.root / "task-state.json")
        self.chat_executor = RecordingChatExecutor()
        self.app = create_app(
            ChatService(self.chat_executor),
            task_manager=self.manager,
        )
        self.output_patch = patch(
            "app.automation.excel.PROJECTS_DIR",
            self.output_dir,
        )
        self.output_patch.start()
        self.client = TestClient(self.app)
        self.client.__enter__()

    @staticmethod
    def _excel_message(filename: str) -> str:
        return (
            f"Crie uma planilha Excel chamada {filename} com os dados: "
            "cabecalhos: Produto, Quantidade, Valor; "
            "linhas: Produto A, 2, 10.5 | Produto B, 1, 7"
        )

    @staticmethod
    def _excel_draft_message(filename: str = "Analise Financeira.xlsx") -> str:
        return (
            f"Jarvis, crie uma planilha Excel chamada {filename} "
            "com uma estrutura para analise de fluxo de caixa."
        )

    @staticmethod
    def _provider_excel_json() -> str:
        return json.dumps(
            {
                "sheet": "Fluxo",
                "headers": ["Data", "Descricao", "Entrada", "Saida"],
                "rows": [
                    ["01/01/2026", "Saldo inicial", 1000, 0],
                    ["02/01/2026", "Pagamento fornecedor", 0, 250],
                ],
            },
            ensure_ascii=False,
        )

    def _post_task_and_wait(self, payload: dict[str, object]) -> dict[str, object]:
        response = self.client.post(
            "/api/tasks",
            json={"type": "excel.create", "payload": payload},
        )
        self.assertEqual(response.status_code, 202)
        task_id = response.json()["task_id"]
        task: dict[str, object] = {}
        for _ in range(100):
            task = self.client.get(f"/api/tasks/{task_id}").json()
            if task["status"] not in {"pending", "running"}:
                return task
            time.sleep(0.01)
        self.fail(f"Task Excel nao terminou: {task_id}")

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.output_patch.stop()
        self.temp_dir.cleanup()

    def test_dispatcher_produces_structured_excel_request_without_submitting(self) -> None:
        dispatcher = ActionDispatcher()

        request = dispatcher.resolve(self._excel_message("Vendas.xlsx"))

        self.assertEqual(
            request,
            ActionRequest(
                action="excel.create",
                arguments={
                    "filename": "Vendas.xlsx",
                    "headers": ["Produto", "Quantidade", "Valor"],
                    "rows": [["Produto A", 2, 10.5], ["Produto B", 1, 7]],
                },
                source="chat",
            ),
        )
        self.assertEqual(self.manager.list(), [])

    def test_chat_excel_request_uses_engine_and_completes_one_verified_task(self) -> None:
        self.assertIs(self.app.state.action_engine.task_manager, self.manager)
        self.assertIs(
            self.app.state.action_registry.resolve("excel.create", source="chat"),
            self.app.state.action_engine.registry.resolve("excel.create", source="chat"),
        )

        response = self.client.post(
            "/api/chat",
            json={"message": self._excel_message("Chat Seguro.xlsx")},
        )

        tasks = self.manager.list()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "completed")
        self.assertEqual(tasks[0]["type"], "excel.create")
        artifact = tasks[0]["result"]["artifacts"][0]
        path = Path(artifact["path"])
        self.assertTrue(artifact["exists"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix.lower(), ".xlsx")
        self.assertGreater(path.stat().st_size, 0)
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            self.assertEqual(
                list(workbook.active.iter_rows(values_only=True)),
                [
                    ("Produto", "Quantidade", "Valor"),
                    ("Produto A", 2, 10.5),
                    ("Produto B", 1, 7),
                ],
            )
        finally:
            workbook.close()
        self.assertIn(f"[file] {path} | {path}", response.text)
        self.assertEqual(self.chat_executor.requests, [])

    def test_rejects_unsafe_filenames_and_requires_xlsx(self) -> None:
        unsafe_names = (
            "sem-extensao",
            "arquivo.xls",
            str((self.root / "absoluto.xlsx").resolve()),
            "pasta/arquivo.xlsx",
            r"pasta\arquivo.xlsx",
            "..xlsx",
            "../traversal.xlsx",
            r"..\traversal.xlsx",
            r"..\Word\arquivo.xlsx",
            r"..\Power BI\arquivo.xlsx",
        )

        for filename in unsafe_names:
            with self.subTest(filename=filename):
                task = self._post_task_and_wait({"filename": filename})
                self.assertEqual(task["status"], "failed")

        self.assertFalse((self.root / "absoluto.xlsx").exists())
        self.assertFalse(self.output_dir.exists())

    def test_existing_workbook_is_not_overwritten_and_content_is_preserved(self) -> None:
        self.output_dir.mkdir(parents=True)
        path = self.output_dir / "Existente.xlsx"
        workbook = Workbook()
        workbook.active["A1"] = "ORIGINAL"
        workbook.save(path)
        before = path.read_bytes()

        task = self._post_task_and_wait(
            {
                "filename": path.name,
                "headers": ["Novo"],
                "rows": [["NAO DEVE GRAVAR"]],
            }
        )

        self.assertEqual(task["status"], "failed")
        self.assertIn("existe", str(task["error"]).lower())
        self.assertEqual(path.read_bytes(), before)
        reopened = load_workbook(path, read_only=True)
        try:
            self.assertEqual(reopened.active["A1"].value, "ORIGINAL")
        finally:
            reopened.close()

    def test_artifact_is_confined_to_projects_root_and_matches_requested_content(self) -> None:
        task = self._post_task_and_wait(
            {
                "filename": "Seguro.xlsx",
                "headers": ["Item", "Quantidade"],
                "rows": [["A", 2], ["B", 3]],
                "sheet": "Auditoria",
            }
        )

        self.assertEqual(task["status"], "completed")
        result = task["result"]
        artifact = result["artifacts"][0]
        path = Path(artifact["path"]).resolve()
        self.assertEqual(path.parent, self.output_dir.resolve())
        self.assertEqual(path, (self.output_dir / "Seguro.xlsx").resolve())
        self.assertTrue(artifact["exists"])
        self.assertEqual(artifact["size"], path.stat().st_size)
        self.assertEqual(artifact["media_type"], XLSX_MEDIA_TYPE)
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            self.assertEqual(workbook.sheetnames, ["Auditoria"])
            self.assertEqual(
                list(workbook["Auditoria"].iter_rows(values_only=True)),
                [("Item", "Quantidade"), ("A", 2), ("B", 3)],
            )
        finally:
            workbook.close()

    def test_path_policy_validates_before_save_and_during_verification(self) -> None:
        calls: list[str] = []
        original_validate = PathPolicy.validate

        def recording_validate(policy, raw_path, *, access):
            calls.append(str(raw_path))
            return original_validate(policy, raw_path, access=access)

        with patch.object(PathPolicy, "validate", new=recording_validate):
            task = self._post_task_and_wait(
                {
                    "filename": "Policy.xlsx",
                    "headers": ["Item"],
                    "rows": [["A"]],
                }
            )

        self.assertEqual(task["status"], "completed")
        self.assertGreaterEqual(len(calls), 3)

    def test_real_verifier_rejects_corrupt_and_divergent_workbooks(self) -> None:
        async def verify(path: Path, arguments: ExcelCreateInput) -> bool:
            definition = create_excel_definition()
            result = ActionResult(
                ok=True,
                action="excel.create",
                artifacts=[
                    ActionArtifact(
                        path=str(path.resolve()),
                        exists=True,
                        size=path.stat().st_size,
                        media_type=XLSX_MEDIA_TYPE,
                    )
                ],
                data={"path": str(path.resolve()), "sheet": "Dados"},
            )
            return await definition.verifier(arguments, result)

        self.output_dir.mkdir(parents=True)
        corrupt = self.output_dir / "Corrompido.xlsx"
        corrupt.write_bytes(b"nao e xlsx")
        self.assertFalse(
            __import__("asyncio").run(
                verify(corrupt, ExcelCreateInput(filename=corrupt.name))
            )
        )

        divergent = self.output_dir / "Divergente.xlsx"
        workbook = Workbook()
        workbook.active.title = "Dados"
        workbook.active.append(["Outro"])
        workbook.active.append(["CONTEUDO DIVERGENTE"])
        workbook.save(divergent)
        self.assertFalse(
            __import__("asyncio").run(
                verify(
                    divergent,
                    ExcelCreateInput(
                        filename=divergent.name,
                        headers=["Esperado"],
                        rows=[["VALOR"]],
                    ),
                )
            )
        )

    def test_dispatcher_creates_excel_draft_only_for_explicit_elaboration(self) -> None:
        dispatcher = ActionDispatcher()
        draft_messages = (
            self._excel_draft_message(),
            (
                "Gere um Excel chamado Controle Estoque.xlsx estruturando um "
                "controle basico de entradas e saidas de estoque."
            ),
            (
                "Crie uma planilha Excel chamada Fornecedores.xlsx para acompanhar "
                "fornecedores, precos, prazos e performance."
            ),
        )
        for message in draft_messages:
            with self.subTest(message=message):
                draft = dispatcher.resolve(message)
                self.assertEqual(type(draft).__name__, "ExcelContentDraft")
                self.assertTrue(draft.filename.endswith(".xlsx"))
                self.assertTrue(draft.instruction)

        conceptual_messages = (
            "O que e Excel?",
            "Voce consegue trabalhar com Excel?",
            "Qual a diferenca entre Word e Excel?",
            "Explique como criar um XLSX.",
            "Como faco uma planilha Excel?",
        )
        for message in conceptual_messages:
            with self.subTest(message=message):
                self.assertIsNone(dispatcher.resolve(message))

    def test_excel_draft_preserves_filename_and_builds_locked_action_request(self) -> None:
        draft = ActionDispatcher().resolve(
            self._excel_draft_message("Nome Controlado.xlsx")
        )
        self.assertIsNotNone(draft)

        action_request = draft.to_action_request(self._provider_excel_json())

        self.assertEqual(action_request.action, "excel.create")
        self.assertEqual(action_request.source, "chat")
        self.assertEqual(
            action_request.arguments,
            {
                "filename": "Nome Controlado.xlsx",
                "sheet": "Fluxo",
                "headers": ["Data", "Descricao", "Entrada", "Saida"],
                "rows": [
                    ["01/01/2026", "Saldo inicial", 1000, 0],
                    ["02/01/2026", "Pagamento fornecedor", 0, 250],
                ],
                "openFile": False,
            },
        )

    def test_elaboration_uses_provider_then_engine_and_real_verifier(self) -> None:
        self.chat_executor.response = self._provider_excel_json()

        response = self.client.post(
            "/api/chat",
            json={"message": self._excel_draft_message("Elaborado.xlsx")},
        )

        tasks = self.manager.list()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.chat_executor.requests), 1)
        self.assertIn(
            "com uma estrutura para analise de fluxo de caixa",
            self.chat_executor.requests[0].message,
        )
        self.assertIn("somente JSON", self.chat_executor.requests[0].message)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["type"], "excel.create")
        self.assertEqual(tasks[0]["status"], "completed")
        self.assertFalse(tasks[0]["result"]["data"]["opened"])
        path = Path(tasks[0]["result"]["artifacts"][0]["path"])
        self.assertEqual(path.name, "Elaborado.xlsx")
        workbook = load_workbook(path, read_only=True, data_only=False)
        try:
            self.assertEqual(workbook.sheetnames, ["Fluxo"])
            self.assertEqual(
                list(workbook["Fluxo"].iter_rows(values_only=True)),
                [
                    ("Data", "Descricao", "Entrada", "Saida"),
                    ("01/01/2026", "Saldo inicial", 1000, 0),
                    ("02/01/2026", "Pagamento fornecedor", 0, 250),
                ],
            )
        finally:
            workbook.close()

    def test_invalid_provider_responses_create_no_task_or_file(self) -> None:
        invalid_responses = {
            "empty": "",
            "provider_error": "[error] Nenhum provider elegivel.",
            "invalid_json": "isto nao e json",
            "markdown": "```json\n{}\n```",
            "extra_filename": json.dumps(
                {
                    "sheet": "Dados",
                    "headers": ["A"],
                    "rows": [[1]],
                    "filename": "Invasor.xlsx",
                }
            ),
            "extra_path": json.dumps(
                {
                    "sheet": "Dados",
                    "headers": ["A"],
                    "rows": [[1]],
                    "path": "C:/fora.xlsx",
                }
            ),
            "mismatched_rows": json.dumps(
                {"sheet": "Dados", "headers": ["A", "B"], "rows": [[1]]}
            ),
            "nested_cell": json.dumps(
                {"sheet": "Dados", "headers": ["A"], "rows": [[{"x": 1}]]}
            ),
            "too_many_columns": json.dumps(
                {
                    "sheet": "Dados",
                    "headers": [f"C{i}" for i in range(51)],
                    "rows": [],
                }
            ),
            "too_many_rows": json.dumps(
                {
                    "sheet": "Dados",
                    "headers": ["A"],
                    "rows": [[i] for i in range(1001)],
                }
            ),
            "oversized_string": json.dumps(
                {"sheet": "Dados", "headers": ["A"], "rows": [["x" * 1001]]}
            ),
        }

        for label, provider_response in invalid_responses.items():
            with self.subTest(label=label):
                self.chat_executor.response = provider_response
                response = self.client.post(
                    "/api/chat",
                    json={
                        "message": self._excel_draft_message(
                            f"Invalido {label}.xlsx"
                        )
                    },
                )
                self.assertIn("[error]", response.text)
                self.assertEqual(self.manager.list(), [])
                self.assertFalse(self.output_dir.exists())

    def test_provider_cannot_override_filename_or_security_fields(self) -> None:
        draft = ActionDispatcher().resolve(
            self._excel_draft_message("Original.xlsx")
        )
        self.assertIsNotNone(draft)
        forbidden_fields = ("filename", "path", "action", "source", "openFile")

        for field in forbidden_fields:
            with self.subTest(field=field):
                payload = json.loads(self._provider_excel_json())
                payload[field] = "invalido"
                with self.assertRaises(Exception):
                    draft.to_action_request(json.dumps(payload))

    def test_provider_error_and_verifier_failure_never_report_false_success(self) -> None:
        self.chat_executor.response = self._provider_excel_json()
        original = create_excel_definition()

        async def rejected(_arguments, _result) -> bool:
            return False

        registry = ActionRegistry()
        registry.register(replace(original, verifier=rejected))
        self.app.state.action_registry = registry
        self.app.state.action_engine = ActionEngine(registry, self.manager)

        response = self.client.post(
            "/api/chat",
            json={"message": self._excel_draft_message("Verifier.xlsx")},
        )

        tasks = self.manager.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "failed")
        self.assertIn("verifier", tasks[0]["error"].lower())
        self.assertIn("[error]", response.text)
        self.assertNotIn("concluida com efeito real", response.text)

    def test_word_and_excel_intents_remain_exclusive(self) -> None:
        dispatcher = ActionDispatcher()
        word = dispatcher.resolve(
            "Crie um arquivo Word chamado Exclusivo.docx com o conteudo: WORD_OK"
        )
        excel = dispatcher.resolve(self._excel_message("Exclusivo.xlsx"))

        self.assertEqual(word.action, "word.create")
        self.assertEqual(excel.action, "excel.create")
        self.assertNotEqual(word.action, excel.action)

    def test_normal_chat_message_bypasses_engine(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={"message": "Responda apenas: CHAT_OK"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "CHAT_FAKE")
        self.assertEqual(len(self.chat_executor.requests), 1)
        self.assertEqual(self.manager.list(), [])

    def test_invalid_excel_schema_creates_no_file_or_task(self) -> None:
        engine = self.app.state.action_engine

        with self.assertRaises(ValidationError):
            engine.submit(
                ActionRequest(
                    action="excel.create",
                    arguments={
                        "filename": "invalid.xlsx",
                        "headers": [],
                        "command": "echo unsafe",
                    },
                    source="chat",
                )
            )

        self.assertEqual(self.manager.list(), [])
        self.assertFalse(self.output_dir.exists())

    def test_excel_cannot_complete_when_real_verifier_rejects_result(self) -> None:
        async def rejected(_arguments, _result) -> bool:
            return False

        async def execute():
            registry = ActionRegistry()
            registry.register(replace(create_excel_definition(), verifier=rejected))
            engine = ActionEngine(registry, self.manager)
            task = engine.submit(
                ActionRequest(
                    action="excel.create",
                    arguments={"filename": "unverified.xlsx"},
                    source="chat",
                )
            )
            return await self.manager.wait(task["task_id"])

        import asyncio

        finished = asyncio.run(execute())
        self.assertEqual(finished["status"], "failed")
        self.assertIn("verifier", finished["error"].lower())

    def test_tasks_endpoint_uses_same_engine_and_registry(self) -> None:
        response = self.client.post(
            "/api/tasks",
            json={
                "type": "excel.create",
                "description": "Criar planilha Excel",
                "payload": {"filename": "Endpoint.xlsx"},
            },
        )

        self.assertEqual(response.status_code, 202)
        task_id = response.json()["task_id"]
        task = None
        for _ in range(50):
            task = self.client.get(f"/api/tasks/{task_id}").json()
            if task["status"] not in {"pending", "running"}:
                break
            time.sleep(0.01)
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["type"], "excel.create")


class ExcelSchemaTests(unittest.TestCase):
    def test_schema_preserves_existing_defaults_and_rejects_unknown_fields(self) -> None:
        payload = ExcelCreateInput()
        self.assertEqual(payload.filename, "Planilha Jarvis.xlsx")
        self.assertFalse(payload.openFile)

        with self.assertRaises(ValidationError):
            ExcelCreateInput.model_validate({"filename": "x.xlsx", "shell": "whoami"})


if __name__ == "__main__":
    unittest.main()
