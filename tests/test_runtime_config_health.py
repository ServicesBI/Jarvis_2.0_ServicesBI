"""Contratos bounded do Módulo 1B — Config / Health."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.executors.availability import ProviderAvailabilityService
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolved_runtime_config(**overrides: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from app.core.config import HOST, LOCAL_ORIGINS, PORT; "
                "print(json.dumps({'host': HOST, 'port': PORT, "
                "'origins': LOCAL_ORIGINS}))"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class CanonicalRuntimeConfigTests(unittest.TestCase):
    def test_safe_defaults_are_localhost_and_port_8000(self) -> None:
        result = _resolved_runtime_config(HOST="127.0.0.1", PORT="8000")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["host"], "127.0.0.1")
        self.assertEqual(json.loads(result.stdout)["port"], 8000)

    def test_environment_host_and_port_are_consumed_by_runtime(self) -> None:
        result = _resolved_runtime_config(HOST="localhost", PORT="8123")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["host"], "localhost")
        self.assertEqual(payload["port"], 8123)
        self.assertEqual(
            payload["origins"],
            ["http://127.0.0.1:8123", "http://localhost:8123"],
        )

    def test_public_bind_from_environment_is_rejected(self) -> None:
        result = _resolved_runtime_config(HOST="0.0.0.0", PORT="8000")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("loopback", result.stderr.lower())

    def test_invalid_port_from_environment_is_rejected(self) -> None:
        result = _resolved_runtime_config(HOST="127.0.0.1", PORT="not-a-port")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("port", result.stderr.lower())

    def test_python_runtime_and_launchers_do_not_define_independent_endpoints(self) -> None:
        launcher_paths = (
            PROJECT_ROOT / "Ligar JARVIS.bat",
            PROJECT_ROOT / "scripts" / "jarvis-python-control.ps1",
            PROJECT_ROOT / "launcher" / "main.js",
        )

        for path in launcher_paths:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("app.core.config", source)
                self.assertNotIn("127.0.0.1:8000", source)

    def test_electron_renderer_does_not_claim_a_fixed_runtime_port(self) -> None:
        source = (PROJECT_ROOT / "launcher" / "renderer" / "renderer.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("porta 8000", source)


class BasicHealthContractTests(unittest.TestCase):
    @staticmethod
    def _client_with_optional_components_unavailable() -> TestClient:
        availability = ProviderAvailabilityService()
        availability.set_state(
            "claude",
            installed=False,
            authenticated=False,
            operational=False,
            entitled=None,
            reason="not_installed",
        )
        application = create_app(availability_service=availability)
        application.state.openai_gateway = type(
            "UnconfiguredGateway", (), {"configured": False}
        )()
        return TestClient(application)

    def test_health_reports_operational_server_identity(self) -> None:
        with self._client_with_optional_components_unavailable() as client:
            payload = client.get("/api/health").json()

        self.assertEqual(payload["components"]["server"]["status"], "ok")

    def test_global_health_is_ok_when_core_server_is_operational(self) -> None:
        with self._client_with_optional_components_unavailable() as client:
            payload = client.get("/api/health").json()

        self.assertEqual(payload["status"], "ok")

    def test_optional_components_do_not_degrade_core_health(self) -> None:
        with self._client_with_optional_components_unavailable() as client:
            payload = client.get("/api/health").json()

        self.assertEqual(payload["components"]["openai"]["status"], "error")
        self.assertNotEqual(payload["components"]["claude"]["status"], "online")
        self.assertEqual(payload["status"], "ok")

    def test_chrome_is_optional_and_not_reported_as_a_hardcoded_error(self) -> None:
        with self._client_with_optional_components_unavailable() as client:
            chrome = client.get("/api/health").json()["components"]["chrome"]

        self.assertEqual(chrome, {"status": "not_checked", "required": False})


if __name__ == "__main__":
    unittest.main()
