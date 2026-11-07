"""Seleção automática testada somente com provedores falsos."""

import asyncio
import unittest
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.executors.availability import (
    AUTO_PROVIDER_PRIORITY,
    ProviderAvailabilityService,
)
from app.executors.cli import CliExecutionResult, CliUnavailableError
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
        self.calls: list[tuple[str, ...]] = []

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        self.calls.append(tuple(arguments))
        if self.error is not None:
            raise self.error
        return self.result


class FakeChatExecutor(ChatExecutor):
    def __init__(
        self,
        response: str = "OpenAI fake",
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        yield self.response


def available(
    service: ProviderAvailabilityService,
    provider: str,
    *,
    operational: bool = True,
    authenticated: bool = True,
    reason: str = "test",
    entitled: bool | None = None,
) -> None:
    service.set_state(
        provider,
        installed=True,
        authenticated=authenticated,
        operational=operational,
        reason=reason,
        entitled=entitled,
    )


class FastAPIAutoModeTest(unittest.TestCase):
    def test_auto_skips_provider_whose_active_profile_is_unavailable(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "codex")
        available(state, "claude")
        manager = ExecutorService("auto")
        manager.set_profile("codex", "max")
        manager.model_registry.set_availability(
            "codex", "max", available=False, reason="model_unavailable"
        )
        codex = FakeCliRunner(CliExecutionResult(0, "NAO", ""))
        claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_OK", ""))
        client = self.make_client(state, manager=manager, codex=codex, claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()
        self.assertEqual(response.text, "CLAUDE_OK")
        self.assertEqual(codex.calls, [])
        self.assertEqual(len(claude.calls), 1)
    def make_client(
        self,
        availability: ProviderAvailabilityService,
        *,
        manager: ExecutorService | None = None,
        codex: FakeCliRunner | None = None,
        claude: FakeCliRunner | None = None,
        openai: FakeChatExecutor | None = None,
    ) -> TestClient:
        return TestClient(
            create_app(
                executor_manager=manager or ExecutorService("auto"),
                availability_service=availability,
                codex_runner=codex or FakeCliRunner(),
                claude_runner=claude or FakeCliRunner(),
                openai_executor=openai,
            )
        )

    def test_priority_is_codex_then_claude(self) -> None:
        self.assertEqual(AUTO_PROVIDER_PRIORITY, ("codex", "claude"))

    def test_status_probes_separate_codex_and_claude_operational_state(self) -> None:
        state = ProviderAvailabilityService()

        async def connected_status():
            return {"installed": True, "connected": True}

        state.register_status_probe(
            "codex",
            connected_status,
            authentication_implies_operational=True,
        )
        state.register_status_probe(
            "claude",
            connected_status,
            authentication_implies_operational=False,
        )
        asyncio.run(state.refresh())

        codex = state.get_state("codex")
        claude = state.get_state("claude")
        self.assertTrue(codex.installed)
        self.assertTrue(codex.authenticated)
        self.assertTrue(codex.operational)
        self.assertTrue(codex.eligible)
        self.assertTrue(claude.installed)
        self.assertTrue(claude.authenticated)
        self.assertFalse(claude.operational)
        self.assertFalse(claude.eligible)

    def test_auto_selects_codex_when_available(self) -> None:
        state = ProviderAvailabilityService()
        for provider in AUTO_PROVIDER_PRIORITY:
            available(state, provider)
        codex = FakeCliRunner(CliExecutionResult(0, "CODEX_AUTO", ""))
        claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_AUTO", ""))
        openai = FakeChatExecutor("OPENAI_AUTO")
        client = self.make_client(state, codex=codex, claude=claude, openai=openai)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.text, "CODEX_AUTO")
        self.assertEqual(len(codex.calls), 1)
        self.assertEqual(openai.calls, [])
        self.assertEqual(claude.calls, [])

    def test_auto_falls_back_to_claude_without_using_openai_for_chat(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "codex")
        available(state, "claude")
        codex = FakeCliRunner(error=CliUnavailableError("Codex indisponível"))
        claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_FALLBACK", ""))
        openai = FakeChatExecutor("OPENAI_NAO_DEVE_SER_USADO")
        client = self.make_client(
            state,
            codex=codex,
            claude=claude,
            openai=openai,
        )
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.text, "CLAUDE_FALLBACK")
        self.assertEqual(len(codex.calls), 1)
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(openai.calls, [])
        self.assertFalse(state.get_state("codex").installed)
        self.assertFalse(state.get_state("codex").eligible)

    def test_auto_uses_claude_only_after_real_capability_is_eligible(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude")
        claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_LAST", ""))
        client = self.make_client(state, claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertEqual(response.text, "CLAUDE_LAST")
        self.assertEqual(len(claude.calls), 1)

    def test_claude_without_positive_entitlement_is_not_selected(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude", operational=False, reason="capability_not_validated")
        claude = FakeCliRunner(CliExecutionResult(0, "NÃO DEVERIA EXECUTAR", ""))
        client = self.make_client(state, claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()

        self.assertIn("Nenhum provedor elegível", response.text)
        self.assertEqual(claude.calls, [])

    def test_auto_lazily_validates_authenticated_entitled_claude(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude", operational=False, reason="capability_not_validated", entitled=True)
        claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_COLD_START", ""))
        client = self.make_client(state, claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()
        self.assertEqual(response.text, "CLAUDE_COLD_START")
        self.assertEqual(len(claude.calls), 1)
        self.assertTrue(state.get_state("claude").operational)
        self.assertEqual(state.get_state("claude").reason, "operational")

    def test_manual_claude_does_not_run_when_not_authenticated(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude", operational=False, authenticated=False, reason="not_authenticated", entitled=True)
        claude = FakeCliRunner(CliExecutionResult(0, "NAO", ""))
        client = self.make_client(state, manager=ExecutorService("claude"), claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()
        self.assertTrue(response.text.startswith("[error]"))
        self.assertEqual(claude.calls, [])

    def test_manual_claude_does_not_run_when_entitlement_is_unavailable(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude", operational=False, reason="plan_unavailable", entitled=False)
        claude = FakeCliRunner(CliExecutionResult(0, "NAO", ""))
        client = self.make_client(state, manager=ExecutorService("claude"), claude=claude)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
        finally:
            client.close()
        self.assertTrue(response.text.startswith("[error]"))
        self.assertEqual(claude.calls, [])

    def test_claude_blocked_by_plan_is_removed_from_auto(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude")
        claude = FakeCliRunner(
            CliExecutionResult(1, "Current plan does not include Claude Code", "")
        )
        manager = ExecutorService("claude")
        client = self.make_client(state, manager=manager, claude=claude)
        try:
            manual = client.post("/api/chat", json={"message": "teste manual"})
            manager.set_mode("auto")
            automatic = client.post("/api/chat", json={"message": "teste auto"})
        finally:
            client.close()

        self.assertIn("[error]", manual.text)
        self.assertIn("Nenhum provedor elegível", automatic.text)
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(state.get_state("claude").reason, "plan_unavailable")
        self.assertFalse(state.get_state("claude").eligible)

    def test_claude_oauth_401_is_not_eligible_for_auto(self) -> None:
        state = ProviderAvailabilityService()
        available(state, "claude")
        claude = FakeCliRunner(
            CliExecutionResult(
                1,
                "Failed to authenticate. API Error: 401 OAuth access token has expired.",
                "",
            )
        )
        manager = ExecutorService("claude")
        client = self.make_client(state, manager=manager, claude=claude)
        try:
            manual = client.post("/api/chat", json={"message": "teste manual"})
            manager.set_mode("auto")
            automatic = client.post("/api/chat", json={"message": "teste auto"})
        finally:
            client.close()

        self.assertIn("[error]", manual.text)
        self.assertIn("Nenhum provedor elegível", automatic.text)
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(state.get_state("claude").reason, "authentication_failed")
        self.assertFalse(state.get_state("claude").authenticated)
        self.assertFalse(state.get_state("claude").eligible)

    def test_no_available_provider_returns_safe_error_and_keeps_fastapi_alive(self) -> None:
        state = ProviderAvailabilityService()
        client = self.make_client(state)
        try:
            response = client.post("/api/chat", json={"message": "teste"})
            health = client.get("/api/health")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.text,
            "[error] Nenhum provedor elegível está disponível no momento.\n",
        )
        self.assertEqual(health.status_code, 200)

    def test_supported_manual_modes_ignore_auto_eligibility_and_keep_working(self) -> None:
        cases = (
            ("codex", "CODEX_MANUAL"),
            ("claude", "CLAUDE_MANUAL"),
        )
        for mode, expected in cases:
            with self.subTest(mode=mode):
                state = ProviderAvailabilityService()
                codex = FakeCliRunner(CliExecutionResult(0, "CODEX_MANUAL", ""))
                claude = FakeCliRunner(CliExecutionResult(0, "CLAUDE_MANUAL", ""))
                openai = FakeChatExecutor("OPENAI_MANUAL")
                client = self.make_client(
                    state,
                    manager=ExecutorService(mode),
                    codex=codex,
                    claude=claude,
                    openai=openai,
                )
                try:
                    response = client.post("/api/chat", json={"message": "teste"})
                finally:
                    client.close()

                self.assertEqual(response.text, expected)

    def test_fastapi_starts_without_providers_or_subprocesses(self) -> None:
        state = ProviderAvailabilityService()
        mocked_spawn = AsyncMock(side_effect=AssertionError("não deveria executar"))
        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            client = self.make_client(state)
            try:
                health = client.get("/api/health")
            finally:
                client.close()

        self.assertEqual(health.status_code, 200)
        mocked_spawn.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
