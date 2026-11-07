"""Contract tests for the read-only Provider Manager API."""

from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.executors.availability import ProviderAvailabilityService
from app.main import create_app
from app.providers.factory import create_provider_manager
from app.providers.manager import ProviderManager
from app.providers.models import (
    AdapterKind,
    AuthMethod,
    Capability,
    ProviderAction,
    ProviderCategory,
    ProviderDefinition,
    ProviderRuntimeState,
)


EXPECTED_IDS = (
    "claude",
    "codex",
    "erp-generic",
    "gemini",
    "google-account",
    "microsoft-account",
    "openai",
    "powerbi",
    "vscode",
)


def fake_definition(provider_id: str = "fake-provider") -> ProviderDefinition:
    return ProviderDefinition(
        id=provider_id,
        name="Fake Provider",
        category=ProviderCategory.SYSTEM,
        description="Provider used only by an isolated test.",
        capabilities=(Capability.LOCAL_TOOL,),
        auth_methods=(AuthMethod.LOCAL,),
        supports_multiple_accounts=False,
        adapter_kind=AdapterKind.LOCAL,
        automatic_allowed_default=False,
        actions=(ProviderAction.STATUS,),
    )


class BombAdapter:
    def __init__(self, definition: ProviderDefinition) -> None:
        self.definition = definition
        self.status_calls = 0

    async def status(self) -> ProviderRuntimeState:
        self.status_calls += 1
        raise AssertionError("GET must not invoke adapter I/O")

    def describe_capabilities(self) -> tuple[Capability, ...]:
        return self.definition.capabilities


class ProviderApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = create_provider_manager()
        self.client = TestClient(create_app(provider_manager=self.manager))

    def tearDown(self) -> None:
        self.client.close()

    def test_catalog_contains_exact_initial_provider_ids(self) -> None:
        self.assertEqual(
            tuple(item.id for item in self.manager.list_definitions()), EXPECTED_IDS
        )

    def test_list_returns_200_and_nonempty_catalog(self) -> None:
        response = self.client.get("/api/providers")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()["count"], 0)

    def test_list_has_deterministic_id_order(self) -> None:
        providers = self.client.get("/api/providers").json()["providers"]
        self.assertEqual(tuple(item["id"] for item in providers), EXPECTED_IDS)

    def test_list_count_matches_items(self) -> None:
        payload = self.client.get("/api/providers").json()
        self.assertEqual(payload["count"], len(payload["providers"]))

    def test_detail_returns_existing_provider(self) -> None:
        response = self.client.get("/api/providers/openai")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "openai")

    def test_detail_matches_same_item_from_list(self) -> None:
        listed = {
            item["id"]: item
            for item in self.client.get("/api/providers").json()["providers"]
        }
        self.assertEqual(
            self.client.get("/api/providers/openai").json(), listed["openai"]
        )

    def test_missing_detail_returns_404_without_internal_details(self) -> None:
        response = self.client.get("/api/providers/missing-provider")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Provider not found."})

    def test_public_schema_uses_explicit_whitelist(self) -> None:
        provider = self.client.get("/api/providers/openai").json()
        self.assertEqual(
            set(provider),
            {
                "id",
                "name",
                "category",
                "description",
                "capabilities",
                "auth_methods",
                "supports_multiple_accounts",
                "adapter_kind",
                "display_status",
                "runtime_state",
                "available_actions",
                "automatic_allowed",
            },
        )
        self.assertEqual(
            set(provider["runtime_state"]),
            {
                "installed",
                "configured",
                "authenticated",
                "connected",
                "reachable",
                "operational",
                "automatic_allowed",
                "entitled",
                "eligible",
                "reason",
                "checked_at",
                "last_error_code",
                "last_error_message",
            },
        )

    def test_enums_are_serialized_as_stable_strings(self) -> None:
        provider = self.client.get("/api/providers/openai").json()
        self.assertEqual(provider["category"], "ai")
        self.assertEqual(provider["adapter_kind"], "python")
        self.assertIn("chat", provider["capabilities"])
        self.assertIn("api_key", provider["auth_methods"])

    def test_unimplemented_catalog_provider_is_not_operational(self) -> None:
        provider = self.client.get("/api/providers/openai").json()
        self.assertEqual(provider["display_status"], "not_installed")
        self.assertFalse(provider["runtime_state"]["operational"])
        self.assertEqual(provider["available_actions"], [])

    def test_only_get_is_exposed_on_collection(self) -> None:
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(
                    getattr(self.client, method)("/api/providers").status_code, 405
                )

    def test_only_get_is_exposed_on_detail(self) -> None:
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(
                    getattr(self.client, method)("/api/providers/openai").status_code,
                    405,
                )

    def test_manager_is_explicitly_injectable(self) -> None:
        manager = ProviderManager()
        manager.register_definition(fake_definition())
        with TestClient(create_app(provider_manager=manager)) as client:
            payload = client.get("/api/providers").json()
        self.assertIs(client.app.state.provider_manager, manager)
        self.assertEqual([item["id"] for item in payload["providers"]], ["fake-provider"])

    def test_category_filter_is_case_insensitive(self) -> None:
        payload = self.client.get("/api/providers?category=AI").json()
        self.assertGreater(payload["count"], 0)
        self.assertTrue(all(item["category"] == "ai" for item in payload["providers"]))

    def test_capability_filter_is_case_insensitive(self) -> None:
        payload = self.client.get("/api/providers?capability=CHAT").json()
        self.assertGreater(payload["count"], 0)
        self.assertTrue(
            all("chat" in item["capabilities"] for item in payload["providers"])
        )

    def test_combined_filters_are_applied(self) -> None:
        payload = self.client.get(
            "/api/providers?category=AI&capability=VISION"
        ).json()
        self.assertEqual(
            [item["id"] for item in payload["providers"]], ["gemini", "openai"]
        )

    def test_invalid_category_filter_returns_400(self) -> None:
        response = self.client.get("/api/providers?category=unknown")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Invalid provider category."})

    def test_invalid_capability_filter_returns_400(self) -> None:
        response = self.client.get("/api/providers?capability=unknown")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Invalid provider capability."})

    def test_reads_do_not_call_adapter_status_or_other_io(self) -> None:
        manager = ProviderManager()
        definition = fake_definition("provider-no-io")
        adapter = BombAdapter(definition)
        manager.register_definition(definition)
        manager.register_adapter(definition.id, adapter)
        with TestClient(create_app(provider_manager=manager)) as client:
            self.assertEqual(client.get("/api/providers").status_code, 200)
            self.assertEqual(client.get("/api/providers/provider-no-io").status_code, 200)
        self.assertEqual(adapter.status_calls, 0)

    def test_fake_error_is_sanitized_in_public_snapshot(self) -> None:
        manager = ProviderManager()
        manager.register_definition(fake_definition())
        manager.record_success("fake-provider")
        manager.record_failure(
            "fake-provider", RuntimeError("api_key=private password=never")
        )
        with TestClient(create_app(provider_manager=manager)) as client:
            payload = client.get("/api/providers/fake-provider").json()
        self.assertEqual(payload["runtime_state"]["last_error_code"], "operation_failed")
        self.assertEqual(
            payload["runtime_state"]["last_error_message"],
            "Provider operation failed.",
        )
        self.assertNotIn("private", json.dumps(payload))
        self.assertNotIn("never", json.dumps(payload))

    def test_json_contains_no_secret_reference_fields_or_material(self) -> None:
        payload = self.client.get("/api/providers").json()
        encoded = json.dumps(payload).lower()
        self.assertNotRegex(
            encoded,
            r'"(?:credential_ref|token|secret|password|api_key|refresh_token)"\s*:',
        )
        self.assertNotRegex(encoded, r'bearer\s+|sk-[a-z0-9]|github_pat_')

    def test_repeated_reads_have_stable_json_bytes(self) -> None:
        first = self.client.get("/api/providers")
        second = self.client.get("/api/providers")
        self.assertEqual(first.content, second.content)

    def test_factory_returns_independent_manager_instances(self) -> None:
        first = create_provider_manager()
        second = create_provider_manager()
        first.set_automatic_allowed("openai", False)
        self.assertFalse(first.get_snapshot("openai").runtime_state.automatic_allowed)
        self.assertTrue(second.get_snapshot("openai").runtime_state.automatic_allowed)


class ProviderApiAvailabilityCoherenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = create_provider_manager()
        self.availability = ProviderAvailabilityService()
        self.client = TestClient(
            create_app(
                provider_manager=self.manager,
                availability_service=self.availability,
            )
        )

    def tearDown(self) -> None:
        self.client.close()

    def _provider(self, provider: str) -> dict[str, object]:
        return self.client.get(f"/api/providers/{provider}").json()

    def test_codex_operational_fields_come_from_chat_availability_authority(self) -> None:
        self.manager.record_success("codex")
        self.availability.set_state(
            "codex",
            installed=False,
            authenticated=False,
            operational=False,
            reason="not_installed",
            entitled=None,
        )

        provider = self._provider("codex")
        state = provider["runtime_state"]

        self.assertFalse(state["installed"])
        self.assertFalse(state["authenticated"])
        self.assertFalse(state["connected"])
        self.assertFalse(state["operational"])
        self.assertFalse(state["eligible"])
        self.assertEqual(state["reason"], "not_installed")
        self.assertEqual(provider["display_status"], "not_installed")

    def test_claude_eligible_does_not_appear_not_installed_without_adapter(self) -> None:
        self.availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            operational=True,
            reason="operational",
            entitled=True,
        )

        provider = self._provider("claude")
        state = provider["runtime_state"]

        self.assertTrue(state["installed"])
        self.assertTrue(state["authenticated"])
        self.assertTrue(state["connected"])
        self.assertTrue(state["entitled"])
        self.assertTrue(state["operational"])
        self.assertTrue(state["eligible"])
        self.assertEqual(state["reason"], "operational")
        self.assertEqual(provider["display_status"], "operational")

    def test_catalog_and_provider_health_share_all_availability_fields(self) -> None:
        self.availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            operational=False,
            reason="capability_not_validated",
            entitled=True,
        )

        catalog = self._provider("claude")["runtime_state"]
        health = self.client.get("/api/providers/health").json()["claude"]

        self.assertEqual(catalog["installed"], health["installed"])
        self.assertEqual(catalog["authenticated"], health["authenticated"])
        self.assertEqual(catalog["connected"], health["connected"])
        self.assertEqual(catalog["entitled"], health["entitled"])
        self.assertEqual(catalog["operational"], health["operational"])
        self.assertEqual(catalog["eligible"], health["eligible"])
        self.assertEqual(catalog["reason"], health["reason"])

    def test_static_catalog_provider_remains_declarative_without_fake_availability(self) -> None:
        provider = self._provider("gemini")

        self.assertEqual(provider["category"], "ai")
        self.assertIn("chat", provider["capabilities"])
        self.assertEqual(provider["display_status"], "not_installed")
        self.assertFalse(provider["runtime_state"]["operational"])


if __name__ == "__main__":
    unittest.main()
