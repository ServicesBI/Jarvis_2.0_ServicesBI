"""Unit tests for the provider domain contract introduced in PASSO 1A."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from app.providers.contracts import (
    ConnectableProviderAdapter,
    ProviderAdapter,
    ProviderDomainError,
    ProviderErrorCode,
)
from app.providers.models import (
    AdapterKind,
    AuthMethod,
    Capability,
    DisplayStatus,
    ProviderAction,
    ProviderCategory,
    ProviderConnection,
    ProviderDefinition,
    ProviderIdentity,
    ProviderRuntimeState,
    derive_display_status,
)


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def make_definition(**overrides: object) -> ProviderDefinition:
    values: dict[str, object] = {
        "id": "openai",
        "name": "OpenAI",
        "category": ProviderCategory.AI,
        "description": "OpenAI API provider.",
        "capabilities": (Capability.CHAT, Capability.TTS),
        "auth_methods": (AuthMethod.API_KEY,),
        "supports_multiple_accounts": True,
        "adapter_kind": AdapterKind.PYTHON,
        "automatic_allowed_default": True,
        "actions": (ProviderAction.STATUS, ProviderAction.EXECUTE),
    }
    values.update(overrides)
    return ProviderDefinition(**values)


class ProviderModelsTest(unittest.TestCase):
    def test_creates_typed_provider_definition(self) -> None:
        provider = make_definition()

        self.assertEqual(provider.id, "openai")
        self.assertEqual(provider.category, ProviderCategory.AI)
        self.assertEqual(provider.capabilities, (Capability.CHAT, Capability.TTS))
        self.assertEqual(provider.auth_methods, (AuthMethod.API_KEY,))

    def test_rejects_invalid_provider_id_and_untyped_category(self) -> None:
        with self.assertRaises(ValueError):
            make_definition(id="OpenAI API")
        with self.assertRaises(TypeError):
            make_definition(category="ai")

    def test_capabilities_are_typed_and_extensible_by_composition(self) -> None:
        provider = make_definition(
            capabilities=(Capability.CHAT, Capability.VISION, Capability.CODE)
        )

        self.assertTrue(provider.supports(Capability.VISION))
        self.assertFalse(provider.supports(Capability.BI))

    def test_connection_contract_has_only_credential_reference(self) -> None:
        connection = ProviderConnection(
            connection_id="openai-work",
            provider_id="openai",
            display_name="Work",
            credential_ref="cred_openai_work",
            created_at=NOW,
            updated_at=NOW,
        )

        payload = connection.to_dict()
        self.assertEqual(payload["credential_ref"], "cred_openai_work")
        self.assertNotIn("api_key", payload)
        self.assertNotIn("token", payload)
        self.assertNotIn("password", payload)

    def test_identity_is_separate_from_service_connection(self) -> None:
        identity = ProviderIdentity(
            identity_id="google-personal",
            provider_id="google",
            display_name="Google pessoal",
            account_hint="u***@example.com",
            scopes=("openid", "email"),
            credential_ref="grant_google_personal",
            created_at=NOW,
            updated_at=NOW,
        )
        connection = ProviderConnection(
            connection_id="drive-personal",
            provider_id="google-drive",
            identity_id=identity.identity_id,
            display_name="Drive pessoal",
            created_at=NOW,
            updated_at=NOW,
        )

        self.assertEqual(connection.identity_id, identity.identity_id)
        self.assertNotEqual(connection.provider_id, identity.provider_id)

    def test_runtime_state_preserves_independent_dimensions(self) -> None:
        state = ProviderRuntimeState(
            provider_id="codex",
            installed=True,
            configured=True,
            authenticated=True,
            reachable=False,
            operational=False,
            automatic_allowed=True,
            checked_at=NOW,
            last_error_code="timeout",
            last_error_message="Provider timed out.",
        )

        self.assertTrue(state.authenticated)
        self.assertFalse(state.reachable)
        self.assertFalse(state.operational)
        self.assertEqual(state.last_error_code, "timeout")

    def test_display_status_is_pure_and_deterministic(self) -> None:
        state = ProviderRuntimeState(
            provider_id="openai", installed=True, configured=True, authenticated=True,
            reachable=True, operational=True, automatic_allowed=True, checked_at=NOW,
        )

        first = derive_display_status(state, now=NOW)
        second = derive_display_status(state, now=NOW)

        self.assertEqual(first, second)
        self.assertEqual(first, DisplayStatus.OPERATIONAL)

    def test_display_status_not_installed(self) -> None:
        state = ProviderRuntimeState(provider_id="codex")
        self.assertEqual(derive_display_status(state, now=NOW), DisplayStatus.NOT_INSTALLED)

    def test_display_status_not_configured(self) -> None:
        state = ProviderRuntimeState(provider_id="openai", installed=True)
        self.assertEqual(derive_display_status(state, now=NOW), DisplayStatus.NOT_CONFIGURED)

    def test_display_status_disconnected(self) -> None:
        state = ProviderRuntimeState(
            provider_id="claude", installed=True, configured=True, authenticated=False
        )
        self.assertEqual(derive_display_status(state, now=NOW), DisplayStatus.DISCONNECTED)

    def test_display_status_expired(self) -> None:
        state = ProviderRuntimeState(
            provider_id="google", installed=True, configured=True, authenticated=True
        )
        self.assertEqual(
            derive_display_status(state, expires_at=NOW - timedelta(seconds=1), now=NOW),
            DisplayStatus.EXPIRED,
        )

    def test_display_status_checking(self) -> None:
        state = ProviderRuntimeState(
            provider_id="openai", installed=True, configured=True, checking=True
        )
        self.assertEqual(derive_display_status(state, now=NOW), DisplayStatus.CHECKING)

    def test_display_status_degraded_and_error_are_distinct(self) -> None:
        degraded = ProviderRuntimeState(
            provider_id="claude", installed=True, configured=True, authenticated=True,
            reachable=False, operational=False,
        )
        failed = ProviderRuntimeState(
            provider_id="claude", installed=True, configured=True, authenticated=True,
            reachable=False, operational=False, last_error_code="execution_failed",
        )

        self.assertEqual(derive_display_status(degraded, now=NOW), DisplayStatus.DEGRADED)
        self.assertEqual(derive_display_status(failed, now=NOW), DisplayStatus.ERROR)

    def test_connected_is_distinct_from_operational(self) -> None:
        connected = ProviderRuntimeState(
            provider_id="google", installed=True, configured=True, authenticated=True,
            reachable=True, operational=False,
        )
        self.assertEqual(derive_display_status(connected, now=NOW), DisplayStatus.CONNECTED)

    def test_serialization_has_stable_enum_and_utc_timestamp_values(self) -> None:
        provider = make_definition()
        connection = ProviderConnection(
            connection_id="openai-work",
            provider_id=provider.id,
            display_name="Work",
            scopes=("models.read",),
            credential_ref="cred_reference_only",
            created_at=NOW,
            updated_at=NOW,
        )

        encoded = json.dumps(connection.to_dict(), sort_keys=True)
        self.assertIn('"2026-08-27T12:00:00Z"', encoded)
        self.assertIn('"credential_ref": "cred_reference_only"', encoded)
        self.assertNotRegex(encoded.lower(), r'api.?key|refresh.?token|password')

    def test_domain_errors_are_distinguished_by_stable_codes(self) -> None:
        error = ProviderDomainError(
            ProviderErrorCode.CAPABILITY_NOT_SUPPORTED,
            "Capability is not supported.",
        )

        self.assertEqual(error.code, ProviderErrorCode.CAPABILITY_NOT_SUPPORTED)
        self.assertEqual(str(error), "Capability is not supported.")


class ProviderAdapterContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_base_adapter_protocol_requires_only_common_operations(self) -> None:
        class StatusOnlyAdapter:
            definition = make_definition(actions=(ProviderAction.STATUS,))

            async def status(self) -> ProviderRuntimeState:
                return ProviderRuntimeState(provider_id="openai", installed=True)

            def describe_capabilities(self) -> tuple[Capability, ...]:
                return self.definition.capabilities

        adapter = StatusOnlyAdapter()

        self.assertIsInstance(adapter, ProviderAdapter)
        self.assertNotIsInstance(adapter, ConnectableProviderAdapter)
        self.assertEqual((await adapter.status()).provider_id, "openai")


if __name__ == "__main__":
    unittest.main()
