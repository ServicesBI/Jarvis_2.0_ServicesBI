"""Unit tests for the thin Codex ProviderManager adapter."""

from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.executors.availability import ProviderAvailabilityService
from app.providers.adapters.codex import CodexProviderAdapter
from app.providers.contracts import (
    ConnectableProviderAdapter,
    DisconnectableProviderAdapter,
    ExecutableProviderAdapter,
    ProviderAdapter,
    ProviderDomainError,
    ProviderErrorCode,
)
from app.providers.factory import PROVIDER_DEFINITIONS
from app.providers.models import Capability


CODEX_DEFINITION = next(item for item in PROVIDER_DEFINITIONS if item.id == "codex")


class FakeAuthService:
    def __init__(
        self,
        status_payload: dict[str, object],
        *,
        status_error: BaseException | None = None,
    ) -> None:
        self.status_payload = status_payload
        self.status_error = status_error
        self.status_calls = 0
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def status(self) -> dict[str, object]:
        self.status_calls += 1
        if self.status_error is not None:
            raise self.status_error
        return dict(self.status_payload)

    async def connect(self) -> dict[str, object]:
        self.connect_calls += 1
        return {"ok": True, "provider": "codex", "status": "connected"}

    async def disconnect(self) -> dict[str, object]:
        self.disconnect_calls += 1
        return {"ok": True, "provider": "codex", "status": "disconnected"}


class FakeExecutor(ChatExecutor):
    def __init__(self, output: str = "codex-result", error: BaseException | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        yield self.output


def status_payload(
    *,
    installed: bool = True,
    connected: bool | None = True,
    status: str = "connected",
    error_code: str | None = None,
) -> dict[str, object]:
    return {
        "provider": "codex",
        "installed": installed,
        "connected": connected,
        "status": status,
        "authMethod": "chatgpt" if connected else None,
        "canConnect": connected is not True,
        "canDisconnect": connected is True,
        "errorCode": error_code,
    }


def make_adapter(
    payload: dict[str, object] | None = None,
    *,
    operational: bool = False,
    status_error: BaseException | None = None,
    executor: FakeExecutor | None = None,
) -> tuple[CodexProviderAdapter, FakeAuthService, FakeExecutor, ProviderAvailabilityService]:
    availability = ProviderAvailabilityService()
    if operational:
        availability.set_state(
            "codex",
            installed=True,
            authenticated=True,
            operational=True,
            reason="operational",
        )
    auth = FakeAuthService(payload or status_payload(), status_error=status_error)
    fake_executor = executor or FakeExecutor()
    adapter = CodexProviderAdapter(
        definition=CODEX_DEFINITION,
        auth_service=auth,
        executor=fake_executor,
        availability=availability,
    )
    return adapter, auth, fake_executor, availability


class CodexProviderAdapterStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_cli_not_installed_maps_all_runtime_dimensions_false(self) -> None:
        adapter, _, _, _ = make_adapter(
            status_payload(installed=False, connected=False, status="not_installed")
        )
        state = await adapter.status()
        self.assertFalse(state.installed)
        self.assertFalse(state.configured)
        self.assertFalse(state.authenticated)
        self.assertFalse(state.reachable)
        self.assertFalse(state.operational)
        self.assertEqual(state.last_error_code, "not_installed")

    async def test_installed_logged_out_is_configured_but_not_authenticated(self) -> None:
        adapter, _, _, _ = make_adapter(
            status_payload(connected=False, status="disconnected")
        )
        state = await adapter.status()
        self.assertTrue(state.installed)
        self.assertTrue(state.configured)
        self.assertFalse(state.authenticated)
        self.assertTrue(state.reachable)
        self.assertFalse(state.operational)
        self.assertIsNone(state.last_error_code)

    async def test_authenticated_without_execution_evidence_is_not_operational(self) -> None:
        adapter, _, _, _ = make_adapter()
        state = await adapter.status()
        self.assertTrue(state.authenticated)
        self.assertTrue(state.reachable)
        self.assertFalse(state.operational)

    async def test_operational_requires_availability_evidence(self) -> None:
        adapter, _, _, _ = make_adapter(operational=True)
        state = await adapter.status()
        self.assertTrue(state.authenticated)
        self.assertTrue(state.operational)

    async def test_status_timeout_has_distinct_sanitized_code(self) -> None:
        adapter, _, _, _ = make_adapter(
            status_payload(connected=None, status="timeout", error_code="status_timeout")
        )
        state = await adapter.status()
        self.assertEqual(state.last_error_code, "status_timeout")
        self.assertEqual(state.last_error_message, "Codex status check timed out.")
        self.assertFalse(state.reachable)

    async def test_status_technical_error_has_distinct_sanitized_code(self) -> None:
        adapter, _, _, _ = make_adapter(
            status_payload(connected=None, status="error", error_code="status_failed")
        )
        state = await adapter.status()
        self.assertEqual(state.last_error_code, "status_failed")
        self.assertEqual(state.last_error_message, "Codex status check failed.")

    async def test_unexpected_auth_exception_is_sanitized(self) -> None:
        adapter, _, _, _ = make_adapter(
            status_error=RuntimeError("access_token=private-value")
        )
        state = await adapter.status()
        encoded = json.dumps(state.to_dict()).lower()
        self.assertEqual(state.last_error_code, "status_failed")
        self.assertNotIn("private-value", encoded)
        self.assertNotIn("access_token", encoded)


class CodexProviderAdapterActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_connect_delegates_then_returns_refreshed_status(self) -> None:
        adapter, auth, _, _ = make_adapter()
        state = await adapter.connect()
        self.assertEqual(auth.connect_calls, 1)
        self.assertEqual(auth.status_calls, 1)
        self.assertTrue(state.authenticated)

    async def test_disconnect_delegates_then_returns_refreshed_status(self) -> None:
        payload = status_payload(connected=False, status="disconnected")
        adapter, auth, _, _ = make_adapter(payload)
        state = await adapter.disconnect()
        self.assertEqual(auth.disconnect_calls, 1)
        self.assertEqual(auth.status_calls, 1)
        self.assertFalse(state.authenticated)

    async def test_execute_chat_delegates_to_existing_executor(self) -> None:
        adapter, _, executor, _ = make_adapter(operational=True)
        result = await adapter.execute(Capability.CHAT, {"message": "hello"})
        self.assertEqual(result, "codex-result")
        self.assertEqual(executor.calls[0].message, "hello")

    async def test_execute_code_uses_same_real_codex_executor_contract(self) -> None:
        adapter, _, executor, _ = make_adapter(operational=True)
        result = await adapter.execute(Capability.CODE, {"message": "inspect code"})
        self.assertEqual(result, "codex-result")
        self.assertEqual(executor.calls[0].message, "inspect code")

    async def test_execute_rejects_unsupported_capability(self) -> None:
        adapter, _, _, _ = make_adapter()
        with self.assertRaises(ProviderDomainError) as context:
            await adapter.execute(Capability.BI, {"message": "no"})
        self.assertEqual(context.exception.code, ProviderErrorCode.CAPABILITY_NOT_SUPPORTED)

    async def test_capabilities_match_existing_definition(self) -> None:
        adapter, _, _, _ = make_adapter()
        self.assertEqual(adapter.describe_capabilities(), (Capability.CHAT, Capability.CODE))

    async def test_adapter_satisfies_only_real_provider_protocols(self) -> None:
        adapter, _, _, _ = make_adapter()
        self.assertIsInstance(adapter, ProviderAdapter)
        self.assertIsInstance(adapter, ConnectableProviderAdapter)
        self.assertIsInstance(adapter, DisconnectableProviderAdapter)
        self.assertIsInstance(adapter, ExecutableProviderAdapter)


if __name__ == "__main__":
    unittest.main()
