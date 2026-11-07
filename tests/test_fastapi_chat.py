"""Caracterização do contrato HTTP e de streaming do chat no PASSO 0E."""

import asyncio
import unittest
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.executors.availability import ProviderAvailabilityService
from app.executors.service import ExecutorService
from app.main import create_app


class FakeChatExecutor(ChatExecutor):
    def __init__(self, chunks: list[str], *, error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.requests: list[ChatRequest] = []
        self.disconnects: list[ChatRequest] = []
        self.closed = False

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        try:
            for chunk in self.chunks:
                await asyncio.sleep(0)
                yield chunk
            if self.error is not None:
                raise self.error
        finally:
            self.closed = True

    async def on_client_disconnect(self, request: ChatRequest) -> None:
        self.disconnects.append(request)


class BlockingFakeChatExecutor(ChatExecutor):
    def __init__(self) -> None:
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.disconnected = False

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        yield "[ack] Recebido.\n"
        self.waiting.set()
        await self.release.wait()
        yield "não deve ser enviado\n"

    async def on_client_disconnect(self, request: ChatRequest) -> None:
        self.disconnected = True


class FastAPIChatContractTest(unittest.TestCase):
    def make_client(self, executor: ChatExecutor) -> TestClient:
        return TestClient(create_app(ChatService(executor)))

    def test_valid_request_preserves_payload_defaults_and_stream_headers(self) -> None:
        executor = FakeChatExecutor(["[ack] Recebido.\n", "Resposta inicial.\n"])
        client = self.make_client(executor)
        try:
            response = client.post("/api/chat", json={"message": "Olá"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "[ack] Recebido.\nResposta inicial.\n")
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(response.headers["transfer-encoding"], "chunked")
        self.assertEqual(
            executor.requests,
            [
                ChatRequest(
                    message="Olá",
                    attachment_id=None,
                    from_voice=False,
                    language="BR",
                    conclave_enabled=True,
                )
            ],
        )

    def test_optional_request_fields_are_accepted_but_not_implemented(self) -> None:
        executor = FakeChatExecutor(["ok"])
        client = self.make_client(executor)
        try:
            response = client.post(
                "/api/chat",
                json={
                    "message": "Analise isto",
                    "attachmentId": "attachment-opaque",
                    "fromVoice": True,
                    "language": "EN",
                    "conclaveEnabled": False,
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(executor.requests[0].attachment_id, "attachment-opaque")
        self.assertTrue(executor.requests[0].from_voice)
        self.assertEqual(executor.requests[0].language, "EN")
        self.assertFalse(executor.requests[0].conclave_enabled)

    def test_invalid_request_returns_node_compatible_400_before_streaming(self) -> None:
        executor = FakeChatExecutor(["não deve executar"])
        client = self.make_client(executor)
        try:
            missing = client.post("/api/chat", json={})
            empty = client.post("/api/chat", json={"message": ""})
            malformed = client.post(
                "/api/chat",
                content="{",
                headers={"Content-Type": "application/json"},
            )
        finally:
            client.close()

        for response in (missing, empty, malformed):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "Message required"})
        self.assertEqual(executor.requests, [])

    def test_multiple_frontend_markers_pass_through_without_reformatting(self) -> None:
        chunks = [
            "[ack] Vou iniciar.\n",
            "\n[build-start]\n",
            "[task-1] primeira parte\n",
            "[info] progresso\n",
            "[file] relatorio.txt | C:/saida/relatorio.txt\n",
            "[system] done\n",
        ]
        executor = FakeChatExecutor(chunks)
        service = ChatService(executor)

        async def collect() -> list[str]:
            async def connected() -> bool:
                return False

            return [chunk async for chunk in service.stream(ChatRequest("teste"), connected)]

        streamed_chunks = asyncio.run(collect())

        self.assertEqual(streamed_chunks, chunks)
        self.assertIn("[build-start]", "".join(streamed_chunks))
        self.assertIn("[task-1]", "".join(streamed_chunks))

    def test_error_after_stream_start_becomes_error_marker_with_http_200(self) -> None:
        executor = FakeChatExecutor(["primeiro chunk\n"], error=RuntimeError("falha simulada"))
        client = self.make_client(executor)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.text,
            "primeiro chunk\n[error] Erro de execução: falha simulada\n",
        )

    def test_fastapi_works_without_any_provider(self) -> None:
        mocked_spawn = AsyncMock()
        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            client = TestClient(
                create_app(
                    executor_manager=ExecutorService("auto"),
                    availability_service=ProviderAvailabilityService(),
                )
            )
            try:
                health_response = client.get("/api/health")
                chat_response = client.post("/api/chat", json={"message": "Olá"})
            finally:
                client.close()

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(chat_response.status_code, 200)
        self.assertTrue(chat_response.text.startswith("[error]"))
        mocked_spawn.assert_not_awaited()


class ChatServiceDisconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_stops_http_chunks_and_notifies_executor(self) -> None:
        executor = FakeChatExecutor(["primeiro\n", "segundo\n"])
        service = ChatService(executor)
        probe_results = iter((False, False, True))

        async def disconnect_probe() -> bool:
            return next(probe_results)

        chunks = [
            chunk
            async for chunk in service.stream(ChatRequest("teste"), disconnect_probe)
        ]

        self.assertEqual(chunks, ["primeiro\n"])
        self.assertEqual(executor.disconnects, [ChatRequest("teste")])
        self.assertTrue(executor.closed)

    async def test_stream_task_cancellation_is_propagated_and_notifies_executor(self) -> None:
        executor = BlockingFakeChatExecutor()
        service = ChatService(executor)

        async def connected() -> bool:
            return False

        async def consume() -> None:
            async for _ in service.stream(ChatRequest("teste"), connected):
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(executor.waiting.wait(), timeout=1)
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(executor.disconnected)


if __name__ == "__main__":
    unittest.main()
