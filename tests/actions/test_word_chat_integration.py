from __future__ import annotations

import tempfile
import unittest
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

from app.actions.engine import ActionEngine
from app.actions.excel import create_excel_definition
from app.actions.models import ActionRequest
from app.actions.registry import ActionRegistry
from app.actions.word import create_word_definition
from app.chat.action_dispatcher import ActionDispatcher
from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.main import create_app
from app.tasks.manager import TaskManager


class RecordingChatExecutor(ChatExecutor):
    def __init__(self, response: str = "Conteudo elaborado pelo provider.") -> None:
        self.response = response
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        yield self.response


class WordDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = ActionDispatcher()

    def assert_word_request(
        self,
        message: str,
        *,
        filename: str,
        content: str,
    ) -> None:
        request = self.dispatcher.resolve(message)
        self.assertIsInstance(request, ActionRequest)
        self.assertEqual(request.action, "word.create")
        self.assertEqual(request.source, "chat")
        self.assertEqual(
            request.arguments,
            {"filename": filename, "content": content},
        )

    def test_extracts_word_filename_and_explicit_content_variations(self) -> None:
        cases = (
            (
                "Crie um documento Word chamado Relatorio Financeiro com o conteúdo: Fluxo de caixa atualizado.",
                "Relatorio Financeiro.docx",
                "Fluxo de caixa atualizado.",
            ),
            (
                "Crie um DOCX chamado Analise Compras contendo uma análise dos fornecedores.",
                "Analise Compras.docx",
                "uma análise dos fornecedores.",
            ),
            (
                "Gere um arquivo Word chamado Resumo.docx com o texto: Resultado aprovado.",
                "Resumo.docx",
                "Resultado aprovado.",
            ),
            (
                "Crie no Word um arquivo chamado Teste com o conteúdo Olá mundo.",
                "Teste.docx",
                "Olá mundo.",
            ),
            (
                "Jarvis, crie um arquivo Word chamado Teste Jarvis com o conteúdo: OK",
                "Teste Jarvis.docx",
                "OK",
            ),
        )
        for message, filename, content in cases:
            with self.subTest(message=message):
                self.assert_word_request(
                    message,
                    filename=filename,
                    content=content,
                )

    def test_docx_filename_does_not_duplicate_extension(self) -> None:
        self.assert_word_request(
            "Crie um DOCX chamado Resultado.docx com o conteúdo: Aprovado",
            filename="Resultado.docx",
            content="Aprovado",
        )

    def test_elaboration_request_is_recognized_without_literal_instruction_content(self) -> None:
        draft = self.dispatcher.resolve(
            "Jarvis, crie um arquivo Word chamado Teste Jarvis explicando suas funções."
        )

        self.assertIsNotNone(draft)
        self.assertNotIsInstance(draft, ActionRequest)
        self.assertEqual(draft.filename, "Teste Jarvis.docx")
        self.assertEqual(draft.instruction, "explicando suas funções.")

    def test_conceptual_word_questions_do_not_dispatch_actions(self) -> None:
        messages = (
            "O que é um arquivo Word?",
            "Você consegue trabalhar com Word?",
            "Qual a diferença entre Word e Excel?",
            "Explique como criar um DOCX.",
        )
        for message in messages:
            with self.subTest(message=message):
                self.assertIsNone(self.dispatcher.resolve(message))

    def test_excel_and_word_intents_remain_separate(self) -> None:
        excel = self.dispatcher.resolve(
            "Crie uma planilha Excel chamada Separacao.xlsx com os dados: "
            "cabecalhos: Item, Valor; linhas: A, 1"
        )
        word = self.dispatcher.resolve(
            "Crie um arquivo Word chamado Documento com o conteúdo: Texto"
        )

        self.assertEqual(excel.action, "excel.create")
        self.assertNotEqual(excel.action, "word.create")
        self.assertEqual(word.action, "word.create")
        self.assertNotEqual(word.action, "excel.create")

    def test_dangerous_filename_is_preserved_for_word_security_validation(self) -> None:
        for filename in (r"..\arquivo.docx", r"C:\temp\arquivo.docx", "pasta/arquivo.docx"):
            with self.subTest(filename=filename):
                request = self.dispatcher.resolve(
                    f"Crie um Word chamado {filename} com o conteúdo: Não gravar"
                )
                self.assertEqual(request.arguments["filename"], filename)


class WordChatIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output_dir = self.root / "Documents and Projects"
        self.manager = TaskManager(self.root / "task-state.json")
        self.executor = RecordingChatExecutor()
        self.app = create_app(
            ChatService(self.executor),
            task_manager=self.manager,
        )
        registry = ActionRegistry()
        registry.register(create_excel_definition())
        registry.register(create_word_definition(projects_root=self.output_dir))
        self.app.state.action_registry = registry
        self.app.state.action_engine = ActionEngine(registry, self.manager)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_explicit_word_request_uses_action_engine_and_real_verifier(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "message": "Jarvis, crie um arquivo Word chamado Integracao com o conteúdo: CONTEUDO_OK"
            },
        )

        tasks = self.manager.list()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["type"], "word.create")
        self.assertEqual(tasks[0]["status"], "completed")
        self.assertEqual(tasks[0]["result"]["action"], "word.create")
        artifact = tasks[0]["result"]["artifacts"][0]
        path = Path(artifact["path"])
        self.assertTrue(artifact["exists"])
        self.assertTrue(path.is_file())
        self.assertEqual([p.text for p in Document(path).paragraphs], ["CONTEUDO_OK"])
        self.assertIn(f"[file] {path} | {path}", response.text)
        self.assertEqual(self.executor.requests, [])

    def test_elaboration_uses_existing_chat_provider_before_action_engine(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "message": "Jarvis, crie um arquivo Word chamado Funcoes explicando suas funções e especificações."
            },
        )

        tasks = self.manager.list()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.executor.requests), 1)
        self.assertIn("explicando suas funções e especificações", self.executor.requests[0].message)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "completed")
        path = Path(tasks[0]["result"]["artifacts"][0]["path"])
        paragraphs = [paragraph.text for paragraph in Document(path).paragraphs]
        self.assertEqual(paragraphs, ["Conteudo elaborado pelo provider."])
        self.assertNotEqual(paragraphs, ["explicando suas funções e especificações."])

    def test_provider_error_during_elaboration_creates_no_task_or_file(self) -> None:
        self.executor.response = "[error] Provider indisponível.\n"

        response = self.client.post(
            "/api/chat",
            json={
                "message": "Crie um Word chamado Sem Provider explicando o sistema."
            },
        )

        self.assertIn("[error] Provider indisponível.", response.text)
        self.assertEqual(self.manager.list(), [])
        self.assertFalse(self.output_dir.exists())

    def test_unsafe_filename_fails_task_without_false_success(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "message": r"Crie um Word chamado ..\arquivo.docx com o conteúdo: Não gravar"
            },
        )

        tasks = self.manager.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "failed")
        self.assertIn("[error]", response.text)
        self.assertNotIn("concluida com efeito real", response.text)
        self.assertFalse(self.output_dir.exists())

    def test_rejected_verifier_is_reported_as_failure(self) -> None:
        definition = create_word_definition(projects_root=self.output_dir)

        async def rejected(_arguments, _result) -> bool:
            return False

        registry = ActionRegistry()
        registry.register(replace(definition, verifier=rejected))
        self.app.state.action_registry = registry
        self.app.state.action_engine = ActionEngine(registry, self.manager)

        response = self.client.post(
            "/api/chat",
            json={
                "message": "Crie um Word chamado Rejeitado com o conteúdo: Não aprovar"
            },
        )

        tasks = self.manager.list()
        self.assertEqual(tasks[0]["status"], "failed")
        self.assertIn("verifier", tasks[0]["error"].lower())
        self.assertIn("[error]", response.text)
        self.assertNotIn("concluida com efeito real", response.text)


if __name__ == "__main__":
    unittest.main()
