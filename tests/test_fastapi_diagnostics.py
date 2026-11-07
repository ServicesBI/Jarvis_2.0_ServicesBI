"""Caracterização das rotas de diagnóstico migradas no PASSO 0C."""

import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import diagnostics
from app.executors.availability import ProviderAvailabilityService
from app.executors.service import ExecutorService
from app.main import app, create_app


class FastAPIDiagnosticsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_stats_matches_frozen_contract(self) -> None:
        response = self.client.get("/api/stats")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"uptime", "uptime_seconds", "started_at", "tokensIn", "tokensOut", "tokens", "requests", "plan", "lastLatency", "pool"},
        )
        self.assertEqual(set(payload["pool"]), {"opus", "sonnet", "haiku"})
        self.assertGreaterEqual(payload["uptime"], 0)
        self.assertGreaterEqual(payload["uptime_seconds"], 0)
        self.assertIsInstance(payload["started_at"], str)
        self.assertEqual(payload["tokens"], payload["tokensIn"] + payload["tokensOut"])

    def test_stats_uptime_grows_without_new_backend_instance(self) -> None:
        first = self.client.get("/api/stats").json()
        time.sleep(0.02)
        second = self.client.get("/api/stats").json()
        self.assertEqual(first["started_at"], second["started_at"])
        self.assertGreaterEqual(second["uptime"], first["uptime"])

    def test_system_stats_matches_frozen_contract(self) -> None:
        expected = {
            "cpu": {"name": None, "usage": 12, "temp": None, "cores": 8},
            "gpu": {"name": None, "temp": None, "vram": None, "usage": None},
            "ram": {"usage": 44, "total": 32, "free": 18, "type": None},
            "source": "psutil",
        }
        with patch("app.core.diagnostics.collect_system_stats", return_value=expected):
            response = self.client.get("/api/system-stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_system_stats_degrades_when_psutil_is_unavailable(self) -> None:
        with patch.dict("sys.modules", {"psutil": None}):
            payload = diagnostics.collect_system_stats()

        self.assertEqual(payload["source"], "python-only")
        self.assertEqual(set(payload), {"cpu", "gpu", "ram", "source"})
        self.assertIsNone(payload["cpu"]["usage"])

    def test_providers_health_matches_frozen_contract_without_executors(self) -> None:
        cleared_environment = {
            "OPENAI_API_KEY": "",
            "JARVIS_CLAUDE_CMD": "claude-missing-for-test",
            "JARVIS_CODEX_CMD": "codex-missing-for-test",
            "JARVIS_EXECUTOR_MODE": "auto",
        }
        with (
            patch.dict(os.environ, cleared_environment),
            patch("app.executors.cli.shutil.which", return_value=None),
        ):
            response = self.client.get("/api/providers/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"server", "api", "voice", "claude", "codex", "executor"})
        self.assertEqual(payload["server"], "ok")
        self.assertEqual(payload["api"]["status"], "error")
        self.assertEqual(payload["voice"]["status"], "error")
        self.assertEqual(payload["claude"]["status"], "offline")
        self.assertEqual(payload["codex"]["status"], "offline")
        self.assertFalse(payload["claude"]["operational"])
        self.assertFalse(payload["codex"]["operational"])
        self.assertEqual(payload["executor"]["validModes"], ["auto", "claude", "codex"])
        self.assertTrue(payload["executor"]["fallbackEnabled"])

    def test_active_provider_health_never_uses_legacy_cli_detection(self) -> None:
        with patch.object(
            ExecutorService,
            "detect_executors",
            side_effect=AssertionError("legacy CLI detection must stay inactive"),
        ):
            response = self.client.get("/api/providers/health")

        self.assertEqual(response.status_code, 200)

    def test_fallback_enabled_is_derived_from_execution_mode(self) -> None:
        for mode, expected in (("auto", True), ("codex", False), ("claude", False)):
            with self.subTest(mode=mode):
                manager = ExecutorService(mode)
                client = TestClient(create_app(executor_manager=manager))
                try:
                    payload = client.get("/api/providers/health").json()
                finally:
                    client.close()

                self.assertIs(payload["executor"]["fallbackEnabled"], expected)

    def test_openai_gateway_remains_available_outside_chat_modes(self) -> None:
        client = TestClient(create_app(executor_manager=ExecutorService("auto")))
        try:
            health = client.get("/api/health")
            modes = client.get("/api/executor/mode")
        finally:
            client.close()

        self.assertEqual(health.status_code, 200)
        self.assertIn("openai", health.json()["components"])
        self.assertNotIn("openai", modes.json()["validModes"])

    def test_providers_health_projects_authoritative_runtime_state(self) -> None:
        availability = ProviderAvailabilityService()
        for provider in ("codex", "claude"):
            availability.set_state(
                provider,
                installed=True,
                authenticated=True,
                operational=True,
                reason="operational",
                entitled=True,
            )
        manager = ExecutorService("auto")
        client = TestClient(
            create_app(
                executor_manager=manager,
                availability_service=availability,
            )
        )
        try:
            before = client.get("/api/providers/health")
            changed = client.post("/api/executor/mode", json={"mode": "claude"})
            after = client.get("/api/providers/health")
        finally:
            client.close()

        self.assertEqual(before.status_code, 200)
        self.assertEqual(changed.json(), {"ok": True, "mode": "claude"})
        for payload in (before.json(), after.json()):
            for provider in ("codex", "claude"):
                with self.subTest(provider=provider):
                    self.assertEqual(payload[provider]["status"], "online")
                    self.assertTrue(payload[provider]["installed"])
                    self.assertTrue(payload[provider]["connected"])
                    self.assertTrue(payload[provider]["authenticated"])
                    self.assertTrue(payload[provider]["operational"])
                    self.assertTrue(payload[provider]["eligible"])
                    self.assertTrue(payload[provider]["entitled"])
                    self.assertEqual(payload[provider]["reason"], "operational")
        self.assertEqual(before.json()["executor"]["mode"], "auto")
        self.assertEqual(after.json()["executor"]["mode"], "claude")


if __name__ == "__main__":
    unittest.main()
