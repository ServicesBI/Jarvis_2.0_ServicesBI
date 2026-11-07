"""Deterministic unit tests for the in-memory ProviderManager."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from app.providers.contracts import ProviderDomainError, ProviderErrorCode
from app.providers.manager import ProviderManager, ProviderSnapshot
from app.providers.models import (
    AdapterKind,
    AuthMethod,
    Capability,
    DisplayStatus,
    ProviderAction,
    ProviderCategory,
    ProviderDefinition,
    ProviderRuntimeState,
)


NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)


def definition(
    provider_id: str = "provider-a",
    *,
    category: ProviderCategory = ProviderCategory.AI,
    capabilities: tuple[Capability, ...] = (Capability.CHAT,),
    actions: tuple[ProviderAction, ...] = (ProviderAction.STATUS,),
    automatic_allowed: bool = True,
) -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        name=provider_id.upper(),
        category=category,
        description=f"Fake definition for {provider_id}.",
        capabilities=capabilities,
        auth_methods=(AuthMethod.CUSTOM,),
        supports_multiple_accounts=True,
        adapter_kind=AdapterKind.PYTHON,
        automatic_allowed_default=automatic_allowed,
        actions=actions,
    )


def runtime(provider_id: str, **overrides: object) -> ProviderRuntimeState:
    values: dict[str, object] = {
        "provider_id": provider_id,
        "installed": True,
        "configured": True,
        "authenticated": True,
        "reachable": True,
        "operational": True,
        "automatic_allowed": True,
        "checked_at": None,
    }
    values.update(overrides)
    return ProviderRuntimeState(**values)


class StatusAdapter:
    def __init__(
        self,
        provider_definition: ProviderDefinition,
        state: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.definition = provider_definition
        self.state = state if state is not None else runtime(provider_definition.id)
        self.error = error
        self.status_calls = 0

    async def status(self) -> ProviderRuntimeState:
        self.status_calls += 1
        if self.error is not None:
            raise self.error
        return self.state  # type: ignore[return-value]

    def describe_capabilities(self) -> tuple[Capability, ...]:
        return self.definition.capabilities


class FullAdapter(StatusAdapter):
    async def connect(self) -> ProviderRuntimeState:
        return runtime(self.definition.id)

    async def disconnect(self) -> ProviderRuntimeState:
        return runtime(self.definition.id, authenticated=False, operational=False)

    async def test_capability(self, capability: Capability) -> ProviderRuntimeState:
        return runtime(self.definition.id)

    async def refresh_auth(self) -> ProviderRuntimeState:
        return runtime(self.definition.id)

    async def execute(self, capability: Capability, payload: object) -> object:
        return payload


class ProviderManagerRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ProviderManager(clock=lambda: NOW)

    def test_empty_manager_has_no_definitions_or_snapshots(self) -> None:
        self.assertEqual(self.manager.list_definitions(), ())
        self.assertEqual(self.manager.list_snapshots(), ())

    def test_registers_and_gets_provider_definition(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)

        self.assertIs(self.manager.get_definition(provider.id), provider)

    def test_rejects_duplicate_provider_id(self) -> None:
        self.manager.register_definition(definition())

        with self.assertRaises(ProviderDomainError) as context:
            self.manager.register_definition(definition())

        self.assertEqual(context.exception.code, ProviderErrorCode.OPERATION_FAILED)

    def test_unknown_provider_uses_domain_error(self) -> None:
        with self.assertRaises(ProviderDomainError) as context:
            self.manager.get_definition("missing-provider")

        self.assertEqual(context.exception.code, ProviderErrorCode.PROVIDER_NOT_FOUND)

    def test_lists_providers_in_deterministic_id_order(self) -> None:
        self.manager.register_definition(definition("provider-b"))
        self.manager.register_definition(definition("provider-a"))

        self.assertEqual(
            tuple(item.id for item in self.manager.list_definitions()),
            ("provider-a", "provider-b"),
        )

    def test_filters_by_category(self) -> None:
        self.manager.register_definition(definition("provider-ai"))
        self.manager.register_definition(
            definition("provider-cloud", category=ProviderCategory.CLOUD)
        )

        result = self.manager.list_definitions(category=ProviderCategory.CLOUD)

        self.assertEqual(tuple(item.id for item in result), ("provider-cloud",))

    def test_filters_by_capability(self) -> None:
        self.manager.register_definition(definition("provider-chat"))
        self.manager.register_definition(
            definition("provider-bi", capabilities=(Capability.BI,))
        )

        result = self.manager.list_definitions(capability=Capability.BI)

        self.assertEqual(tuple(item.id for item in result), ("provider-bi",))

    def test_capability_checks_and_domain_error(self) -> None:
        self.manager.register_definition(definition())

        self.assertTrue(self.manager.supports_capability("provider-a", Capability.CHAT))
        self.assertFalse(self.manager.supports_capability("provider-a", Capability.BI))
        with self.assertRaises(ProviderDomainError) as context:
            self.manager.require_capability("provider-a", Capability.BI)
        self.assertEqual(
            context.exception.code, ProviderErrorCode.CAPABILITY_NOT_SUPPORTED
        )

    def test_registers_adapter_and_rejects_unknown_provider(self) -> None:
        provider = definition()
        adapter = StatusAdapter(provider)
        self.manager.register_definition(provider)

        self.manager.register_adapter(provider.id, adapter)
        with self.assertRaises(ProviderDomainError) as context:
            self.manager.register_adapter("missing-provider", adapter)

        self.assertEqual(context.exception.code, ProviderErrorCode.PROVIDER_NOT_FOUND)

    def test_rejects_inconsistent_or_duplicate_adapter_unless_replace_is_explicit(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)
        first = StatusAdapter(provider)
        second = StatusAdapter(provider)
        self.manager.register_adapter(provider.id, first)

        with self.assertRaises(ProviderDomainError):
            self.manager.register_adapter(provider.id, second)

        mismatched = StatusAdapter(definition("provider-b"))
        with self.assertRaises(ProviderDomainError):
            self.manager.register_adapter(provider.id, mismatched, replace=True)

        self.manager.register_adapter(provider.id, second, replace=True)

    def test_rejects_object_that_does_not_satisfy_base_adapter_protocol(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)

        with self.assertRaises(ProviderDomainError) as context:
            self.manager.register_adapter(provider.id, object())

        self.assertEqual(context.exception.code, ProviderErrorCode.OPERATION_FAILED)

    def test_provider_without_adapter_has_explicit_unimplemented_snapshot(self) -> None:
        self.manager.register_definition(definition())

        snapshot = self.manager.get_snapshot("provider-a")

        self.assertEqual(snapshot.display_status, DisplayStatus.NOT_INSTALLED)
        self.assertEqual(snapshot.available_actions, ())
        self.assertFalse(snapshot.runtime_state.installed)

    def test_automatic_allowed_can_be_changed_without_mutating_definition(self) -> None:
        provider = definition(automatic_allowed=True)
        self.manager.register_definition(provider)

        snapshot = self.manager.set_automatic_allowed(provider.id, False)

        self.assertFalse(snapshot.runtime_state.automatic_allowed)
        self.assertTrue(provider.automatic_allowed_default)

    def test_snapshot_is_immutable_and_serializes_without_sensitive_fields(self) -> None:
        self.manager.register_definition(definition())
        snapshot = self.manager.get_snapshot("provider-a")

        with self.assertRaises(FrozenInstanceError):
            snapshot.display_status = DisplayStatus.ERROR  # type: ignore[misc]
        encoded = json.dumps(snapshot.to_dict(), sort_keys=True).lower()
        self.assertNotRegex(encoded, r'api.?key|refresh.?token|password|secret')


class ProviderManagerRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = ProviderManager(clock=lambda: NOW)

    async def test_refresh_validates_and_stores_runtime_snapshot(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)
        self.manager.register_adapter(provider.id, StatusAdapter(provider))

        snapshot = await self.manager.refresh_provider(provider.id)

        self.assertEqual(snapshot.runtime_state.checked_at, NOW)
        self.assertEqual(snapshot.display_status, DisplayStatus.OPERATIONAL)
        self.assertEqual(self.manager.get_snapshot(provider.id), snapshot)

    async def test_refresh_uses_contract_1a_display_derivation(self) -> None:
        provider = definition()
        adapter = StatusAdapter(
            provider,
            runtime(provider.id, authenticated=False, operational=False),
        )
        self.manager.register_definition(provider)
        self.manager.register_adapter(provider.id, adapter)

        snapshot = await self.manager.refresh_provider(provider.id)

        self.assertEqual(snapshot.display_status, DisplayStatus.DISCONNECTED)

    async def test_invalid_status_result_becomes_sanitized_failure(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)
        self.manager.register_adapter(provider.id, StatusAdapter(provider, state={}))

        snapshot = await self.manager.refresh_provider(provider.id)

        self.assertEqual(snapshot.runtime_state.last_error_code, "invalid_status_result")
        self.assertEqual(
            snapshot.runtime_state.last_error_message,
            "Provider status check returned an invalid result.",
        )

    async def test_adapter_error_is_recorded_without_leaking_exception_text(self) -> None:
        provider = definition()
        adapter = StatusAdapter(
            provider,
            error=RuntimeError("token=private-value password=never-expose"),
        )
        self.manager.register_definition(provider)
        self.manager.register_adapter(provider.id, adapter)

        snapshot = await self.manager.refresh_provider(provider.id)
        encoded = json.dumps(snapshot.to_dict()).lower()

        self.assertEqual(snapshot.runtime_state.last_error_code, "status_check_failed")
        self.assertIn("status check failed", encoded)
        self.assertNotIn("private-value", encoded)
        self.assertNotIn("never-expose", encoded)

    async def test_one_adapter_failure_does_not_affect_other_provider(self) -> None:
        failed = definition("provider-a")
        healthy = definition("provider-b")
        self.manager.register_definition(failed)
        self.manager.register_definition(healthy)
        self.manager.register_adapter(failed.id, StatusAdapter(failed, error=RuntimeError()))
        self.manager.register_adapter(healthy.id, StatusAdapter(healthy))

        snapshots = await self.manager.refresh_all()

        by_id = {snapshot.definition.id: snapshot for snapshot in snapshots}
        self.assertEqual(by_id["provider-a"].runtime_state.last_error_code, "status_check_failed")
        self.assertEqual(by_id["provider-b"].display_status, DisplayStatus.OPERATIONAL)

    async def test_available_actions_are_protocol_state_and_definition_aware(self) -> None:
        all_actions = tuple(ProviderAction)
        provider = definition(actions=all_actions)
        self.manager.register_definition(provider)
        self.manager.register_adapter(provider.id, FullAdapter(provider))

        before = self.manager.get_snapshot(provider.id)
        after = await self.manager.refresh_provider(provider.id)

        self.assertEqual(
            before.available_actions,
            (ProviderAction.STATUS, ProviderAction.CONNECT),
        )
        self.assertEqual(
            after.available_actions,
            (
                ProviderAction.STATUS,
                ProviderAction.DISCONNECT,
                ProviderAction.TEST,
                ProviderAction.REFRESH,
                ProviderAction.EXECUTE,
            ),
        )

    async def test_adapter_capabilities_must_match_registered_definition(self) -> None:
        provider = definition()

        class InconsistentCapabilitiesAdapter(StatusAdapter):
            def describe_capabilities(self) -> tuple[Capability, ...]:
                return (Capability.BI,)

        self.manager.register_definition(provider)
        with self.assertRaises(ProviderDomainError):
            self.manager.register_adapter(
                provider.id, InconsistentCapabilitiesAdapter(provider)
            )

    async def test_record_success_updates_central_state(self) -> None:
        self.manager.register_definition(definition())

        snapshot = self.manager.record_success("provider-a")

        self.assertTrue(snapshot.runtime_state.operational)
        self.assertEqual(snapshot.runtime_state.checked_at, NOW)
        self.assertEqual(snapshot.display_status, DisplayStatus.OPERATIONAL)

    async def test_record_failure_preserves_registry_and_sanitizes_error(self) -> None:
        provider = definition()
        self.manager.register_definition(provider)
        self.manager.record_success(provider.id)

        snapshot = self.manager.record_failure(
            provider.id, RuntimeError("api_key=private-value")
        )

        self.assertFalse(snapshot.runtime_state.operational)
        self.assertEqual(snapshot.runtime_state.last_error_code, "operation_failed")
        self.assertEqual(snapshot.runtime_state.last_error_message, "Provider operation failed.")
        self.assertNotIn("private-value", json.dumps(snapshot.to_dict()))

    async def test_refresh_all_includes_provider_without_adapter(self) -> None:
        with_adapter = definition("provider-a")
        without_adapter = definition("provider-b")
        self.manager.register_definition(with_adapter)
        self.manager.register_definition(without_adapter)
        adapter = StatusAdapter(with_adapter)
        self.manager.register_adapter(with_adapter.id, adapter)

        snapshots = await self.manager.refresh_all()

        self.assertEqual(tuple(item.definition.id for item in snapshots), ("provider-a", "provider-b"))
        self.assertEqual(adapter.status_calls, 1)
        self.assertEqual(snapshots[1].display_status, DisplayStatus.NOT_INSTALLED)


if __name__ == "__main__":
    unittest.main()
