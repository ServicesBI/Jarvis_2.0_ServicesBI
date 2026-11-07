"""Contratos migrados da cadeia de voz, sem chamadas externas pagas."""

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.openai_gateway import UpstreamError
from app.actions.models import ActionResult
from app.executors.availability import ProviderAvailabilityService
from app.main import create_app
from app.tasks.manager import TaskManager


class FakeGateway:
    def __init__(self, *, configured=True, failure=None):
        self.configured = configured
        self.failure = failure
        self.transcriptions = ["create a useful report"]
        self.realtime_requests = []
        self.realtime_result = {"value": "ephemeral-test", "expires_at": 123456}

    async def create_realtime_session(self, **kwargs):
        self.realtime_requests.append(kwargs)
        if self.failure:
            raise self.failure
        return self.realtime_result

    async def transcribe(self, *args, **kwargs):
        if self.failure:
            raise self.failure
        return self.transcriptions.pop(0)

    async def synthesize(self, **kwargs):
        if self.failure:
            raise self.failure
        return b"ID3-test-audio"

    async def complete(self, **kwargs):
        if self.failure:
            raise self.failure
        messages = kwargs["messages"]
        if isinstance(messages[-1]["content"], str):
            return "translated text"
        return "screen description"


class FastAPIVoiceTests(unittest.TestCase):
    def setUp(self):
        self._temp_dirs: list[tempfile.TemporaryDirectory] = []

    def tearDown(self):
        for temp_dir in self._temp_dirs:
            temp_dir.cleanup()

    def _isolated_task_manager(self) -> TaskManager:
        """create_app() sem task_manager= constroi um TaskManager real ligado
        a system/task-state.json (le/reconcilia esse arquivo no __init__).
        Todo create_app() destes testes recebe um TaskManager isolado."""

        temp_dir = tempfile.TemporaryDirectory()
        self._temp_dirs.append(temp_dir)
        return TaskManager(Path(temp_dir.name) / "task-state.json")

    def make_client(self, gateway):
        app = create_app(task_manager=self._isolated_task_manager())
        app.state.openai_gateway = gateway
        app.state.voice_command_handler = lambda message, language: (
            {"summary": "recognized"} if message == "known command" else None
        )
        return TestClient(app), app

    def test_realtime_missing_key(self):
        client, _ = self.make_client(FakeGateway(configured=False))
        response = client.post("/api/realtime/session", json={"language": "BR", "voice": "ash"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "OPENAI_KEY_MISSING")

    def test_local_status_answer_does_not_create_claude_operational_evidence(self):
        availability = ProviderAvailabilityService()
        availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            entitled=True,
            operational=False,
            reason="capability_not_validated",
        )
        client = TestClient(
            create_app(
                availability_service=availability,
                task_manager=self._isolated_task_manager(),
            )
        )
        try:
            response = client.post(
                "/api/voice-command-router",
                json={"message": "o claude esta funcionando?", "language": "BR"},
            )
            state = availability.get_state("claude")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["route"], "fast-path")
        self.assertFalse(state.operational)
        self.assertFalse(state.eligible)
        self.assertEqual(state.reason, "capability_not_validated")

    def test_realtime_success_contract(self):
        gateway = FakeGateway()
        client, _ = self.make_client(gateway)
        response = client.post("/api/realtime/session", json={"language": "BR", "voice": "ash"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["value"], "ephemeral-test")
        self.assertIn("expires_at", response.json())
        self.assertIn("model", response.json())
        self.assertEqual(gateway.realtime_requests[0]["language"], "BR")
        self.assertEqual(gateway.realtime_requests[0]["voice"], "ash")

    def test_realtime_accepts_exact_frontend_voice_set(self):
        voices = ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar")
        gateway = FakeGateway()
        client, _ = self.make_client(gateway)

        for voice in voices:
            with self.subTest(voice=voice):
                response = client.post("/api/realtime/session", json={"language": "BR", "voice": voice})
                self.assertEqual(response.status_code, 200)

        self.assertEqual(tuple(call["voice"] for call in gateway.realtime_requests), voices)

    def test_realtime_normalizes_known_languages(self):
        gateway = FakeGateway()
        client, _ = self.make_client(gateway)

        for supplied, expected in (("br", "BR"), ("es", "ES"), ("en", "EN")):
            with self.subTest(language=supplied):
                response = client.post("/api/realtime/session", json={"language": supplied, "voice": "ash"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(gateway.realtime_requests[-1]["language"], expected)

    def test_realtime_rejects_invalid_voice_and_language_before_gateway(self):
        gateway = FakeGateway()
        client, _ = self.make_client(gateway)

        invalid_voice = client.post("/api/realtime/session", json={"language": "BR", "voice": "nova"})
        invalid_language = client.post("/api/realtime/session", json={"language": "FR", "voice": "ash"})

        self.assertEqual(
            (invalid_voice.status_code, invalid_voice.json().get("code")),
            (400, "INVALID_REALTIME_VOICE"),
        )
        self.assertEqual(
            (invalid_language.status_code, invalid_language.json().get("code")),
            (400, "INVALID_REALTIME_LANGUAGE"),
        )
        self.assertEqual(gateway.realtime_requests, [])

    def test_realtime_session_response_never_returns_permanent_key(self):
        gateway = FakeGateway()
        gateway.realtime_result = {
            "value": "ephemeral-test",
            "expires_at": 123456,
            "OPENAI_API_KEY": "server-only-secret",
        }
        client, _ = self.make_client(gateway)

        response = client.post("/api/realtime/session", json={"language": "BR", "voice": "ash"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"value", "expires_at", "model"})
        self.assertNotIn("server-only-secret", response.text)

    def test_realtime_refused_and_network_failure(self):
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(401, "refused")))
        response = client.post("/api/realtime/session", json={})
        self.assertEqual((response.status_code, response.json()["code"]), (401, "REALTIME_SESSION_REFUSED"))
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(502, "offline")))
        response = client.post("/api/realtime/session", json={})
        self.assertEqual((response.status_code, response.json()["code"]), (502, "REALTIME_UPSTREAM_ERROR"))

    def test_stt_requires_audio_and_transcribes_multipart(self):
        client, _ = self.make_client(FakeGateway())
        self.assertEqual(client.post("/api/stt").status_code, 400)
        response = client.post(
            "/api/stt",
            files={"audio": ("voice.webm", b"a" * 3000, "audio/webm")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"text": "create a useful report"})

    def test_stt_upstream_error(self):
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(429, "rate limited")))
        response = client.post("/api/stt", files={"audio": ("a.webm", b"a" * 3000, "audio/webm")})
        self.assertEqual(response.status_code, 500)

    def test_tts_audio_and_error(self):
        client, _ = self.make_client(FakeGateway())
        response = client.post("/api/tts", json={"text": "Ola", "language": "BR"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.content, b"ID3-test-audio")
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(500, "tts failed")))
        self.assertEqual(client.post("/api/tts", json={"text": "Ola"}).status_code, 500)

    def test_translate_success_and_fallback(self):
        client, _ = self.make_client(FakeGateway())
        self.assertEqual(client.post("/api/translate", json={"text": "ola", "targetLang": "EN"}).json(), {"translated": "translated text"})
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(500, "failed")))
        self.assertEqual(client.post("/api/translate", json={"text": "ola"}).json(), {"translated": "ola"})

    def test_voice_router_recognized_and_fallback(self):
        client, _ = self.make_client(FakeGateway())
        known = client.post("/api/voice-command-router", json={"message": "known command"})
        unknown = client.post("/api/voice-command-router", json={"message": "unknown command"})
        self.assertTrue(known.json()["handled"])
        self.assertEqual(known.json()["route"], "fast-path")
        self.assertEqual(unknown.json(), {"handled": False, "reason": "no_fast_route"})

    def test_default_voice_router_preserves_web_media_and_chat_required_paths(self):
        app = create_app(task_manager=self._isolated_task_manager())
        app.state.openai_gateway = FakeGateway()
        client = TestClient(app)
        with patch("app.api.voice.webbrowser.open", return_value=True) as opened:
            site = client.post("/api/voice-command-router", json={"message": "abre o github", "language": "BR"}).json()
            media = client.post("/api/voice-command-router", json={"message": "toca jazz no spotify", "language": "BR"}).json()
            maps = client.post("/api/voice-command-router", json={"message": "rota para Brasilia", "language": "BR"}).json()
        self.assertEqual(site["route"], "fast-path")
        self.assertEqual(media["route"], "media")
        self.assertEqual(maps["route"], "fast-path")
        self.assertEqual(opened.call_count, 3)
        screen = client.post("/api/voice-command-router", json={"message": "analise minha tela"}).json()
        self.assertEqual(screen, {"handled": False, "reason": "chat_required"})

    def test_voice_dashboard_command_submits_real_powerbi_task_before_acknowledging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            app = create_app(task_manager=manager)
            definition = app.state.action_registry.resolve("powerbi.open", source="chat")

            async def handler(_arguments):
                return ActionResult(
                    ok=True,
                    action="powerbi.open",
                    summary="Power BI controlado.",
                )

            async def verifier(_arguments, _result):
                return True

            app.state.action_registry._definitions["powerbi.open"] = replace(
                definition, handler=handler, verifier=verifier
            )

            with TestClient(app) as client:
                response = client.post(
                    "/api/voice-command-router",
                    json={
                        "message": "Jarvis, abra o dashboard Real X Meta (Recomendações)",
                        "language": "BR",
                    },
                )
                payload = response.json()
                task = manager.get(payload.get("task_id", ""))

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["handled"])
            self.assertEqual(payload["route"], "action")
            self.assertEqual(payload["action"], "powerbi.open")
            self.assertIsNotNone(task)
            self.assertEqual(task["type"], "powerbi.open")
            self.assertIn(task["status"], {"pending", "running", "completed"})

    def test_voice_operational_intent_reports_submission_failure_explicitly(self):
        app = create_app(task_manager=self._isolated_task_manager())
        app.state.action_engine.submit = lambda _request: (_ for _ in ()).throw(
            PermissionError("policy recusou")
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/voice-command-router",
                json={"message": "Jarvis, abra o dashboard Real X Meta (Recomendações)"},
            )

        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertTrue(payload["handled"])
        self.assertEqual(payload["route"], "action-error")
        self.assertIn("policy recusou", payload["summary"])
        self.assertNotRegex(payload["summary"].lower(), r"vou cuidar|vou fazer|abrindo|executando")

    def test_vision_success_and_failure(self):
        client, _ = self.make_client(FakeGateway())
        response = client.post("/api/analyze-screen-fast", json={"image": "data:image/png;base64,AA=="})
        self.assertEqual(response.json(), {"response": "screen description"})
        self.assertEqual(client.post("/api/analyze-screen", json={}).status_code, 400)
        client, _ = self.make_client(FakeGateway(failure=UpstreamError(500, "vision failed")))
        self.assertEqual(client.post("/api/analyze-screen", json={"image": "data:image/png;base64,AA=="}).status_code, 500)

    def test_notifications_sse_headers_and_initial_event(self):
        client, app = self.make_client(FakeGateway())
        route = next(
            route for included in app.routes
            for route in getattr(getattr(included, "original_router", included), "routes", [])
            if getattr(route, "path", None) == "/api/notifications"
        )
        scope = {"type": "http", "app": app, "method": "GET", "path": "/api/notifications", "headers": [], "client": ("127.0.0.1", 1), "query_string": b""}
        from starlette.requests import Request
        response = asyncio.run(route.endpoint(Request(scope)))
        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        stream = response.body_iterator
        self.assertEqual(asyncio.run(stream.__anext__()), b'data: {"type":"connected"}\n\n')
        asyncio.run(stream.aclose())


if __name__ == "__main__":
    unittest.main()
