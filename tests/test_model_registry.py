import unittest

from app.executors.model_registry import (
    DEFAULT_MODEL_PROFILE,
    ModelProfile,
    ModelRegistry,
    ModelUnavailableError,
)


class ModelRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ModelRegistry.default()

    def test_codex_profiles_resolve_to_validated_models(self) -> None:
        expected = {
            "max": "gpt-5.6-sol",
            "pro": "gpt-5.6-terra",
            "fast": "gpt-5.6-luna",
        }
        for profile, model_id in expected.items():
            with self.subTest(profile=profile):
                resolution = self.registry.resolve("codex", profile)
                self.assertEqual(resolution.model_id, model_id)
                self.assertTrue(resolution.available)
                self.assertTrue(resolution.enabled)

    def test_claude_profiles_resolve_only_to_models_proven_by_smoke(self) -> None:
        expected = {"max": "opus", "pro": "sonnet", "fast": "haiku"}
        for profile, model_id in expected.items():
            with self.subTest(profile=profile):
                self.assertEqual(
                    self.registry.resolve("claude", profile).model_id,
                    model_id,
                )

    def test_default_profile_is_centralized_and_balanced(self) -> None:
        self.assertIs(DEFAULT_MODEL_PROFILE, ModelProfile.PRO)

    def test_invalid_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.resolve("codex", "ultra")

    def test_provider_without_mapping_is_explicitly_unavailable(self) -> None:
        with self.assertRaises(ModelUnavailableError) as raised:
            self.registry.resolve("openai", "pro")
        self.assertEqual(raised.exception.reason, "profile_unavailable")

    def test_disabled_model_is_not_resolved_and_has_reason(self) -> None:
        self.registry.set_availability(
            "codex", "max", available=False, reason="model_unavailable"
        )
        with self.assertRaises(ModelUnavailableError) as raised:
            self.registry.resolve("codex", "max")
        self.assertEqual(raised.exception.reason, "model_unavailable")

    def test_unauthorized_model_is_distinct(self) -> None:
        self.registry.set_availability(
            "claude", "max", available=False, reason="model_unauthorized"
        )
        with self.assertRaises(ModelUnavailableError) as raised:
            self.registry.resolve("claude", "max")
        self.assertEqual(raised.exception.reason, "model_unauthorized")

    def test_public_catalog_is_sanitized_and_complete(self) -> None:
        catalog = self.registry.catalog()
        expected_display_names = {
            "codex": {"max": "GPT-5.6 Sol", "pro": "GPT-5.6 Terra", "fast": "GPT-5.6 Luna"},
            "claude": {"max": "Opus 5", "pro": "Sonnet 5", "fast": "Haiku 4.5"},
        }
        self.assertEqual(set(catalog), {"codex", "claude"})
        for provider_name, provider in catalog.items():
            self.assertEqual(set(provider), {"max", "pro", "fast"})
            for profile_name, profile in provider.items():
                self.assertEqual(
                    set(profile), {"profile", "display_name", "available", "enabled", "reason", "status"}
                )
                self.assertEqual(profile["display_name"], expected_display_names[provider_name][profile_name])
                self.assertNotIn("model_id", profile)


if __name__ == "__main__":
    unittest.main()
