"""Autenticação Codex testada somente com subprocesso e detecção falsos."""

import json
import unittest
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.executors.cli import CliDetection, CliExecutionResult, CliTimeoutError
from app.executors.codex_auth import CodexAuthService
from app.executors.service import ExecutorService
from app.main import create_app


class FakeAuthRunner:
    def __init__(
        self,
        result: CliExecutionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result or CliExecutionResult(0, "", "")
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        self.calls.append(
            {
                "arguments": tuple(arguments),
                "timeout": timeout,
                "cwd": cwd,
                "stdin_text": stdin_text,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def fake_detection(available: bool):
    def detect(provider: str, command: str) -> CliDetection:
        return CliDetection(
            provider=provider,
            command=command,
            available=available,
            path=r"C:\tools\codex.exe" if available else None,
        )

    return detect


class FastAPICodexAuthTest(unittest.TestCase):
    def make_client(
        self,
        runner: FakeAuthRunner,
        *,
        installed: bool = True,
    ) -> TestClient:
        service = CodexAuthService(
            "codex",
            runner=runner,
            detector=fake_detection(installed),
        )
        return TestClient(
            create_app(
                executor_manager=ExecutorService("auto"),
                codex_auth_service=service,
            )
        )

    def test_status_reports_not_installed_without_running_codex(self) -> None:
        runner = FakeAuthRunner()
        client = self.make_client(runner, installed=False)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "provider": "codex",
                "installed": False,
                "connected": False,
                "status": "not_installed",
                "authMethod": None,
                "canConnect": False,
                "canDisconnect": False,
            },
        )
        self.assertEqual(runner.calls, [])

    def test_status_uses_official_command_and_returns_only_sanitized_method(self) -> None:
        secret = "access_token=secret-value-never-return"
        runner = FakeAuthRunner(
            CliExecutionResult(0, f"Logged in using ChatGPT\n{secret}", "")
        )
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["connected"])
        self.assertEqual(payload["status"], "connected")
        self.assertEqual(payload["authMethod"], "chatgpt")
        self.assertFalse(payload["canConnect"])
        self.assertTrue(payload["canDisconnect"])
        self.assertNotIn(secret, json.dumps(payload))
        self.assertNotIn("stdout", payload)
        self.assertNotIn("stderr", payload)
        self.assertEqual(runner.calls[0]["arguments"], ("login", "status"))
        self.assertEqual(runner.calls[0]["timeout"], 10.0)

    def test_status_can_identify_api_key_method_without_returning_the_key(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(0, "Logged in using API key sk-secret", "")
        )
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        self.assertEqual(response.json()["authMethod"], "api_key")
        self.assertNotIn("sk-secret", response.text)

    def test_nonzero_status_is_disconnected(self) -> None:
        runner = FakeAuthRunner(CliExecutionResult(1, "Not logged in", ""))
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["connected"])
        self.assertEqual(response.json()["status"], "disconnected")
        self.assertTrue(response.json()["canConnect"])

    def test_status_timeout_has_sanitized_distinct_code(self) -> None:
        runner = FakeAuthRunner(error=CliTimeoutError(10.0, "token=private", "secret"))
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "timeout")
        self.assertEqual(response.json()["errorCode"], "status_timeout")
        self.assertNotIn("private", response.text)

    def test_status_technical_error_has_sanitized_distinct_code(self) -> None:
        runner = FakeAuthRunner(error=RuntimeError("access_token=private"))
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/codex/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "error")
        self.assertEqual(response.json()["errorCode"], "status_failed")
        self.assertNotIn("private", response.text)

    def test_connect_starts_only_official_browser_oauth_command(self) -> None:
        secret_url = "https://auth.openai.example/?token=never-return"
        runner = FakeAuthRunner(CliExecutionResult(0, secret_url, "secret stderr"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/codex/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
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
        self.assertNotIn(secret_url, response.text)
        self.assertNotIn("secret stderr", response.text)
        self.assertEqual(runner.calls[0]["arguments"], ("login",))
        self.assertEqual(runner.calls[0]["timeout"], 300.0)
        self.assertIsNone(runner.calls[0]["stdin_text"])

    def test_disconnect_uses_only_official_logout_command(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(0, "credentials removed secret-value", "")
        )
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/codex/disconnect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "provider": "codex", "status": "disconnected"},
        )
        self.assertNotIn("secret-value", response.text)
        self.assertEqual(runner.calls[0]["arguments"], ("logout",))
        self.assertEqual(runner.calls[0]["timeout"], 30.0)

    def test_connect_returns_503_when_codex_is_absent(self) -> None:
        runner = FakeAuthRunner()
        client = self.make_client(runner, installed=False)
        try:
            response = client.post("/api/integrations/codex/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_installed")
        self.assertEqual(runner.calls, [])

    def test_connect_timeout_returns_sanitized_504(self) -> None:
        runner = FakeAuthRunner(
            error=CliTimeoutError(300.0, "partial secret", "stderr secret")
        )
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/codex/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["status"], "timeout")
        self.assertNotIn("secret", response.text)

    def test_command_failure_returns_sanitized_502(self) -> None:
        runner = FakeAuthRunner(error=RuntimeError("token=internal-secret"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/codex/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["status"], "error")
        self.assertNotIn("internal-secret", response.text)

    def test_workload_identity_logout_is_reported_as_unsupported(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(1, "", "logout rejected for workload identity")
        )
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/codex/disconnect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["status"], "unsupported")
        self.assertNotIn("workload identity", response.text.lower())

    def test_fastapi_starts_without_codex_and_without_auth_subprocess(self) -> None:
        runner = FakeAuthRunner(error=AssertionError("não deveria executar"))
        client = self.make_client(runner, installed=False)
        try:
            response = client.get("/api/health")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(runner.calls, [])

    def test_external_origin_is_rejected_before_any_subprocess(self) -> None:
        runner = FakeAuthRunner()
        client = self.make_client(runner)
        try:
            response = client.post(
                "/api/integrations/codex/connect",
                headers={"Origin": "https://example.com"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
