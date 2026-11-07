"""Integração do chat com Codex por meio de runner falso no PASSO 0F."""

import asyncio
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.chat.codex import CodexChatExecutor, CodexProcessError
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.core.config import PROJECT_ROOT
from app.executors.cli import CliExecutionResult, CliTimeoutError, CliUnavailableError
from app.executors.service import ExecutorService
from app.main import create_app


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
        self.calls.append(
            {
                "arguments": tuple(arguments),
                "timeout": timeout,
                "cwd": cwd,
                "stdin_text": stdin_text,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


class BlockingCliRunner(FakeCliRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = False

    async def execute(self, *args, **kwargs) -> CliExecutionResult:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("runner bloqueante não deveria finalizar")


class FastAPICodexChatTest(unittest.TestCase):
    def make_client(self, runner: FakeCliRunner, mode: str = "codex") -> TestClient:
        return TestClient(
            create_app(
                executor_manager=ExecutorService(mode),
                codex_runner=runner,
            )
        )

    def test_codex_available_is_selected_only_in_codex_mode(self) -> None:
        runner = FakeCliRunner(CliExecutionResult(0, "Codex disponível", ""))
        client = self.make_client(runner)
        try:
            response = client.post("/api/chat", json={"message": "Responda"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Codex disponível")
        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        self.assertEqual(call["stdin_text"], "Responda")
        self.assertEqual(call["timeout"], 90.0)
        self.assertEqual(call["cwd"], PROJECT_ROOT)
        self.assertIn("exec", call["arguments"])
        self.assertIn("read-only", call["arguments"])
        self.assertIn("--ephemeral", call["arguments"])
        model_index = call["arguments"].index("-m")
        self.assertEqual(call["arguments"][model_index + 1], "gpt-5.6-terra")

    def test_selected_max_profile_passes_exact_model_id(self) -> None:
        runner = FakeCliRunner(CliExecutionResult(0, "OK", ""))
        manager = ExecutorService("codex")
        manager.set_profile("codex", "max")
        client = TestClient(create_app(executor_manager=manager, codex_runner=runner))
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()
        self.assertEqual(response.text, "OK")
        arguments = runner.calls[0]["arguments"]
        self.assertEqual(arguments[arguments.index("-m") + 1], "gpt-5.6-sol")

    def test_mode_endpoint_selects_codex_for_the_next_chat_request(self) -> None:
        runner = FakeCliRunner(CliExecutionResult(0, "selecionado pelo manager", ""))
        manager = ExecutorService("auto")
        client = TestClient(
            create_app(executor_manager=manager, codex_runner=runner)
        )
        try:
            mode_response = client.post("/api/executor/mode", json={"mode": "codex"})
            chat_response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(mode_response.json(), {"ok": True, "mode": "codex"})
        self.assertEqual(chat_response.text, "selecionado pelo manager")
        self.assertEqual(len(runner.calls), 1)

    def test_normal_multiline_stdout_preserves_chat_stream_contract(self) -> None:
        output = "Primeira linha.\n[info] segunda linha\n"
        runner = FakeCliRunner(CliExecutionResult(0, output, ""))
        client = self.make_client(runner)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, output)
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(response.headers["transfer-encoding"], "chunked")

    def test_codex_unavailable_becomes_error_chunk_without_crashing_fastapi(self) -> None:
        runner = FakeCliRunner(error=CliUnavailableError("CLI indisponível: codex"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
            health = client.get("/api/health")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "[error] Erro de execução: CLI indisponível: codex\n")
        self.assertEqual(health.status_code, 200)

    def test_stderr_is_captured_on_nonzero_exit_without_exposing_its_contents(self) -> None:
        result = CliExecutionResult(7, "saída parcial", "detalhe interno do stderr")
        executor = CodexChatExecutor(FakeCliRunner(result), cwd=PROJECT_ROOT)

        async def run_once() -> None:
            iterator = executor.stream(ChatRequest("teste"))
            with self.assertRaises(CodexProcessError) as raised:
                await anext(iterator)
            self.assertEqual(raised.exception.returncode, 7)
            self.assertEqual(raised.exception.stdout, "saída parcial")
            self.assertEqual(raised.exception.stderr, "detalhe interno do stderr")
            self.assertNotIn("detalhe interno", str(raised.exception))

        asyncio.run(run_once())

    def test_timeout_becomes_error_chunk(self) -> None:
        runner = FakeCliRunner(
            error=CliTimeoutError(90.0, "saída parcial", "timeout interno")
        )
        client = self.make_client(runner)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn("[error]", response.text)
        self.assertIn("timeout de 90s", response.text)

    def test_subprocess_error_becomes_error_chunk(self) -> None:
        runner = FakeCliRunner(error=RuntimeError("falha simulada do subprocesso"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.text,
            "[error] Erro de execução: falha simulada do subprocesso\n",
        )

    def test_unimplemented_modes_do_not_call_codex_or_implement_fallback(self) -> None:
        for mode in ("auto", "openai"):
            with self.subTest(mode=mode):
                runner = FakeCliRunner()
                client = self.make_client(runner, mode=mode)
                try:
                    response = client.post("/api/chat", json={"message": "teste"})
                finally:
                    client.close()

                self.assertTrue(response.text.startswith("[error]"))
                self.assertEqual(runner.calls, [])

    def test_fastapi_starts_without_codex_and_does_not_spawn_on_startup(self) -> None:
        mocked_spawn = AsyncMock(side_effect=AssertionError("não deveria executar"))
        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            client = TestClient(
                create_app(executor_manager=ExecutorService("auto"))
            )
            try:
                response = client.get("/api/health")
            finally:
                client.close()

        self.assertEqual(response.status_code, 200)
        mocked_spawn.assert_not_awaited()


class CodexChatCancellationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_reaches_runner_and_is_propagated(self) -> None:
        runner = BlockingCliRunner()
        executor = CodexChatExecutor(runner, cwd=PROJECT_ROOT)
        service = ChatService(executor)

        async def connected() -> bool:
            return False

        async def consume() -> None:
            async for _ in service.stream(ChatRequest("teste"), connected):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(runner.started.wait(), timeout=1)
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(runner.cancelled)


if __name__ == "__main__":
    unittest.main()
