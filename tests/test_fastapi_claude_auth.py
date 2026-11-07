"""Autenticação Claude testada somente com subprocessos falsos."""

import json
import unittest
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.executors.claude_auth import ClaudeAuthService
from app.executors.cli import CliDetection, CliExecutionResult, CliTimeoutError
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
            path=r"C:\tools\claude.cmd" if available else None,
        )

    return detect


class FastAPIClaudeAuthTest(unittest.TestCase):
    def make_client(
        self,
        runner: FakeAuthRunner,
        *,
        installed: bool = True,
    ) -> TestClient:
        service = ClaudeAuthService(
            "claude",
            runner=runner,
            detector=fake_detection(installed),
        )
        return TestClient(
            create_app(
                executor_manager=ExecutorService("auto"),
                claude_auth_service=service,
            )
        )

    def test_status_reports_not_installed_without_running_claude(self) -> None:
        runner = FakeAuthRunner()
        client = self.make_client(runner, installed=False)
        try:
            response = client.get("/api/integrations/claude/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "provider": "claude",
                "installed": False,
                "connected": False,
                "status": "not_installed",
                "authMethod": None,
                "apiProvider": None,
                "canConnect": False,
                "canDisconnect": False,
                "entitled": None,
            },
        )
        self.assertEqual(runner.calls, [])

    def test_status_uses_official_json_and_removes_sensitive_fields(self) -> None:
        secret = "token-value-never-return"
        raw_status = json.dumps(
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "apiProvider": "firstParty",
                "email": "private@example.com",
                "orgId": secret,
                "orgName": "Private org",
                "subscriptionType": "max",
            }
        )
        runner = FakeAuthRunner(CliExecutionResult(0, raw_status, secret))
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/claude/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "provider": "claude",
                "installed": True,
                "connected": True,
                "status": "connected",
                "authMethod": "claude.ai",
                "apiProvider": "first_party",
                "canConnect": False,
                "canDisconnect": True,
                "entitled": True,
            },
        )
        self.assertNotIn(secret, response.text)
        self.assertNotIn("private@example.com", response.text)
        self.assertNotIn("stdout", response.text)
        self.assertNotIn("stderr", response.text)
        self.assertEqual(
            runner.calls[0]["arguments"],
            ("auth", "status", "--json"),
        )
        self.assertEqual(runner.calls[0]["timeout"], 10.0)

    def test_status_reports_disconnected_from_official_json(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(1, '{"loggedIn":false}', "not logged in")
        )
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/claude/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["connected"])
        self.assertEqual(response.json()["status"], "disconnected")
        self.assertTrue(response.json()["canConnect"])

    def test_status_with_invalid_json_is_unknown_and_sanitized(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(0, "token=secret-invalid-output", "secret stderr")
        )
        client = self.make_client(runner)
        try:
            response = client.get("/api/integrations/claude/status")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["connected"])
        self.assertEqual(response.json()["status"], "unknown")
        self.assertNotIn("secret", response.text)

    def test_connect_starts_only_official_claudeai_login(self) -> None:
        secret_url = "https://claude.ai/oauth?token=never-return"
        runner = FakeAuthRunner(CliExecutionResult(0, secret_url, "secret stderr"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/claude/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "provider": "claude",
                "status": "connected",
                "authMethod": "claude.ai",
                "flow": "browser_oauth",
            },
        )
        self.assertNotIn(secret_url, response.text)
        self.assertNotIn("secret stderr", response.text)
        self.assertEqual(
            runner.calls[0]["arguments"],
            ("auth", "login", "--claudeai"),
        )
        self.assertEqual(runner.calls[0]["timeout"], 300.0)
        self.assertIsNone(runner.calls[0]["stdin_text"])

    def test_disconnect_uses_only_official_logout(self) -> None:
        runner = FakeAuthRunner(
            CliExecutionResult(0, "removed credential secret-value", "")
        )
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/claude/disconnect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "provider": "claude", "status": "disconnected"},
        )
        self.assertNotIn("secret-value", response.text)
        self.assertEqual(
            runner.calls[0]["arguments"],
            ("auth", "logout"),
        )
        self.assertEqual(runner.calls[0]["timeout"], 30.0)

    def test_connect_returns_503_when_claude_is_absent(self) -> None:
        runner = FakeAuthRunner()
        client = self.make_client(runner, installed=False)
        try:
            response = client.post("/api/integrations/claude/connect")
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
            response = client.post("/api/integrations/claude/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["status"], "timeout")
        self.assertNotIn("secret", response.text)

    def test_command_failure_returns_sanitized_502(self) -> None:
        runner = FakeAuthRunner(error=RuntimeError("token=internal-secret"))
        client = self.make_client(runner)
        try:
            response = client.post("/api/integrations/claude/connect")
        finally:
            client.close()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["status"], "error")
        self.assertNotIn("internal-secret", response.text)

    def test_fastapi_starts_without_claude_and_without_subprocess(self) -> None:
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
                "/api/integrations/claude/connect",
                headers={"Origin": "https://example.com"},
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
