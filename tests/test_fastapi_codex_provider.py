"""ProviderManager and FastAPI integration tests for the Codex adapter."""

from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.executors.availability import ProviderAvailabilityService
from app.executors.cli import CliExecutionResult
from app.executors.service import ExecutorService
from app.main import create_app
from app.providers.adapters.codex import CodexProviderAdapter
from app.providers.factory import PROVIDER_DEFINITIONS, create_provider_manager
from app.providers.models import Capability, DisplayStatus, ProviderAction


CODEX_DEFINITION = next(item for item in PROVIDER_DEFINITIONS if item.id == "codex")


class StatefulAuthService:
    def __init__(
        self,
        *,
        installed: bool = True,
        connected: bool | None = False,
        error_code: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.installed = installed
        self.connected = connected
        self.error_code = error_code
        self.error = error
        self.status_calls = 0
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def status(self) -> dict[str, object]:
        self.status_calls += 1
        if self.error is not None:
            raise self.error
        status = (
            "not_installed"
            if not self.installed
            else "connected"
            if self.connected is True
            else "disconnected"
            if self.connected is False
            else "error"
        )
        return {
            "provider": "codex",
            "installed": self.installed,
            "connected": self.connected,
            "status": status,
            "authMethod": "chatgpt" if self.connected else None,
            "canConnect": self.installed and self.connected is not True,
            "canDisconnect": self.connected is True,
            "errorCode": self.error_code,
        }

    async def connect(self) -> dict[str, object]:
        self.connect_calls += 1
        self.connected = True
        return {
            "ok": True,
            "provider": "codex",
            "status": "connected",
            "authMethod": "chatgpt",
            "flow": "browser_oauth",
        }

    async def disconnect(self) -> dict[str, object]:
        self.disconnect_calls += 1
        self.connected = False
        return {"ok": True, "provider": "codex", "status": "disconnected"}


class NoopExecutor(ChatExecutor):
    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        yield "fake"


class NoSpawnRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        self.calls += 1
        raise AssertionError("Provider GET/startup must use auth status, not chat execution")


class ResultRunner:
    def __init__(
        self,
        result: CliExecutionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result or CliExecutionResult(0, "CODEX_OK", "")
        self.error = error

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        if self.error is not None:
            raise self.error
        return self.result


def adapter_for(
    auth: StatefulAuthService,
    availability: ProviderAvailabilityService | None = None,
) -> CodexProviderAdapter:
    return CodexProviderAdapter(
        definition=CODEX_DEFINITION,
        auth_service=auth,
        executor=NoopExecutor(),
        availability=availability or ProviderAvailabilityService(),
    )


class CodexProviderFactoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_factory_registers_only_injected_codex_adapter(self) -> None:
        auth = StatefulAuthService(connected=False)
        manager = create_provider_manager(codex_adapter=adapter_for(auth))

        codex = manager.get_snapshot("codex")
        others = [
            manager.get_snapshot(item.id)
            for item in manager.list_definitions()
            if item.id != "codex"
        ]

        self.assertEqual(codex.available_actions, (ProviderAction.STATUS, ProviderAction.CONNECT))
        self.assertTrue(all(snapshot.available_actions == () for snapshot in others))

    async def test_refresh_updates_codex_without_affecting_other_providers(self) -> None:
        auth = StatefulAuthService(connected=True)
        manager = create_provider_manager(codex_adapter=adapter_for(auth))

        snapshot = await manager.refresh_provider("codex")

        self.assertTrue(snapshot.runtime_state.authenticated)
        self.assertEqual(snapshot.display_status, DisplayStatus.CONNECTED)
        self.assertEqual(manager.get_snapshot("openai").display_status, DisplayStatus.NOT_INSTALLED)

    async def test_codex_failure_is_sanitized_and_other_snapshots_remain_available(self) -> None:
        auth = StatefulAuthService(error=RuntimeError("access_token=private"))
        manager = create_provider_manager(codex_adapter=adapter_for(auth))

        codex = await manager.refresh_provider("codex")
        openai = manager.get_snapshot("openai")

        self.assertEqual(codex.runtime_state.last_error_code, "status_failed")
        self.assertNotIn("private", json.dumps(codex.to_dict()))
        self.assertEqual(openai.display_status, DisplayStatus.NOT_INSTALLED)


class FastAPICodexProviderTest(unittest.TestCase):
    def make_app(
        self,
        auth: StatefulAuthService,
        *,
        availability: ProviderAvailabilityService | None = None,
    ):
        runner = NoSpawnRunner()
        application = create_app(
            executor_manager=ExecutorService("auto"),
            codex_auth_service=auth,
            codex_runner=runner,
            availability_service=availability or ProviderAvailabilityService(),
        )
        return application, runner

    def test_startup_refreshes_codex_once_and_get_does_not_probe_again(self) -> None:
        auth = StatefulAuthService(connected=True)
        application, runner = self.make_app(auth)

        with TestClient(application) as client:
            first = client.get("/api/providers/codex")
            second = client.get("/api/providers/codex")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["display_status"], "operational")
        self.assertEqual(first.content, second.content)
        self.assertEqual(auth.status_calls, 1)
        self.assertEqual(runner.calls, 0)

    def test_startup_status_failure_does_not_prevent_fastapi_boot(self) -> None:
        auth = StatefulAuthService(error=RuntimeError("token=private"))
        application, _ = self.make_app(auth)

        with TestClient(application) as client:
            health = client.get("/api/health")
            codex = client.get("/api/providers/codex")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(codex.status_code, 200)
        self.assertEqual(codex.json()["runtime_state"]["last_error_code"], "status_probe_failed")
        self.assertNotIn("private", codex.text)

    def test_operational_snapshot_requires_real_availability_evidence(self) -> None:
        availability = ProviderAvailabilityService()
        availability.set_state(
            "codex",
            installed=True,
            authenticated=True,
            operational=True,
            reason="operational",
        )
        auth = StatefulAuthService(connected=True)
        application, _ = self.make_app(auth, availability=availability)

        with TestClient(application) as client:
            response = client.get("/api/providers/codex")

        self.assertTrue(response.json()["runtime_state"]["operational"])
        self.assertEqual(response.json()["display_status"], "operational")

    def test_successful_codex_chat_updates_canonical_availability_state(self) -> None:
        provider_manager = create_provider_manager()
        application = create_app(
            executor_manager=ExecutorService("codex"),
            codex_auth_service=StatefulAuthService(connected=True),
            codex_runner=ResultRunner(),
            availability_service=ProviderAvailabilityService(),
            provider_manager=provider_manager,
        )

        with TestClient(application) as client:
            before = client.get("/api/providers/codex")
            chat = client.post("/api/chat", json={"message": "Responda apenas: CODEX_OK"})
            after = client.get("/api/providers/codex")

        self.assertFalse(before.json()["runtime_state"]["operational"])
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(chat.text, "CODEX_OK")
        self.assertTrue(after.json()["runtime_state"]["operational"])
        self.assertEqual(after.json()["display_status"], "operational")
        self.assertFalse(
            provider_manager.get_snapshot("codex").runtime_state.operational
        )

    def test_failed_codex_chat_updates_canonical_availability_reason(self) -> None:
        application = create_app(
            executor_manager=ExecutorService("codex"),
            codex_auth_service=StatefulAuthService(connected=True),
            codex_runner=ResultRunner(error=RuntimeError("falha simulada")),
            availability_service=ProviderAvailabilityService(),
        )

        with TestClient(application) as client:
            chat = client.post("/api/chat", json={"message": "teste"})
            after = client.get("/api/providers/codex")

        self.assertEqual(chat.status_code, 200)
        self.assertIn("[error]", chat.text)
        self.assertFalse(after.json()["runtime_state"]["operational"])
        self.assertEqual(
            after.json()["runtime_state"]["last_error_code"],
            "execution_failed",
        )

    def test_existing_connect_route_preserves_response_and_refreshes_snapshot(self) -> None:
        auth = StatefulAuthService(connected=False)
        application, _ = self.make_app(auth)

        with TestClient(application) as client:
            response = client.post("/api/integrations/codex/connect")
            snapshot = client.get("/api/providers/codex")

        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "provider": "codex",
                "status": "connected",
                "authMethod": "chatgpt",
                "flow": "browser_oauth",
            },
        )
        self.assertTrue(snapshot.json()["runtime_state"]["authenticated"])
        self.assertEqual(auth.connect_calls, 1)
        self.assertEqual(auth.status_calls, 2)

    def test_existing_disconnect_route_preserves_response_and_refreshes_snapshot(self) -> None:
        auth = StatefulAuthService(connected=True)
        application, _ = self.make_app(auth)

        with TestClient(application) as client:
            response = client.post("/api/integrations/codex/disconnect")
            snapshot = client.get("/api/providers/codex")

        self.assertEqual(
            response.json(),
            {"ok": True, "provider": "codex", "status": "disconnected"},
        )
        self.assertFalse(snapshot.json()["runtime_state"]["authenticated"])
        self.assertEqual(auth.disconnect_calls, 1)
        self.assertEqual(auth.status_calls, 2)


if __name__ == "__main__":
    unittest.main()
