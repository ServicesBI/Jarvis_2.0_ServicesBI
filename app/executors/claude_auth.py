"""Autenticação oficial do Claude Code CLI sem manipular credenciais."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from app.executors.cli import (
    AsyncCliExecutor,
    CliDetection,
    CliExecutionResult,
    CliTimeoutError,
    CliUnavailableError,
    detect_cli,
)


class AuthCliRunner(Protocol):
    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult: ...


class ClaudeAuthError(RuntimeError):
    """Erro público controlado de uma operação de autenticação."""


class ClaudeNotInstalledError(ClaudeAuthError):
    """O Claude Code CLI não está disponível no PATH configurado."""


class ClaudeAuthTimeoutError(ClaudeAuthError):
    """O fluxo oficial não terminou dentro do limite configurado."""


class ClaudeAuthCommandError(ClaudeAuthError):
    """O comando oficial terminou sem sucesso."""


Detector = Callable[[str, str], CliDetection]


class ClaudeAuthService:
    """Executa somente ``claude auth status/login/logout``."""

    def __init__(
        self,
        command: str,
        *,
        runner: AuthCliRunner | None = None,
        detector: Detector | None = None,
        status_timeout: float = 10.0,
        login_timeout: float = 300.0,
        logout_timeout: float = 30.0,
    ) -> None:
        self.command = command
        self.runner = (
            runner
            if runner is not None
            else AsyncCliExecutor(command, default_timeout=login_timeout)
        )
        self.detector = detector if detector is not None else detect_cli
        self.status_timeout = status_timeout
        self.login_timeout = login_timeout
        self.logout_timeout = logout_timeout

    def _detection(self) -> CliDetection:
        return self.detector("Claude", self.command)

    async def status(self) -> dict[str, object]:
        """Retorna somente campos sanitizados do JSON oficial de status."""

        if not self._detection().available:
            return self._status_payload(
                installed=False,
                connected=False,
                status="not_installed",
            )

        try:
            result = await self.runner.execute(
                ("auth", "status", "--json"),
                timeout=self.status_timeout,
            )
        except CliUnavailableError:
            return self._status_payload(
                installed=False,
                connected=False,
                status="not_installed",
            )
        except CliTimeoutError:
            return self._status_payload(
                installed=True,
                connected=None,
                status="unknown",
            )
        except Exception:
            return self._status_payload(
                installed=True,
                connected=None,
                status="unknown",
            )

        status_data = self._parse_status(result.stdout)
        if status_data is None:
            if result.returncode != 0:
                return self._status_payload(
                    installed=True,
                    connected=False,
                    status="disconnected",
                )
            return self._status_payload(
                installed=True,
                connected=None,
                status="unknown",
            )

        logged_in = status_data.get("loggedIn")
        if logged_in is not True:
            return self._status_payload(
                installed=True,
                connected=False,
                status="disconnected",
            )

        return self._status_payload(
            installed=True,
            connected=True,
            status="connected",
            auth_method=self._safe_auth_method(status_data.get("authMethod")),
            api_provider=self._safe_api_provider(status_data.get("apiProvider")),
            entitled=self._safe_entitlement(status_data.get("subscriptionType")),
        )

    async def connect(self) -> dict[str, object]:
        """Inicia o OAuth oficial da assinatura Claude.ai no navegador."""

        self._require_installed()
        result = await self._execute_auth_command(
            ("auth", "login", "--claudeai"),
            self.login_timeout,
        )
        if result.returncode != 0:
            raise ClaudeAuthCommandError
        return {
            "ok": True,
            "provider": "claude",
            "status": "connected",
            "authMethod": "claude.ai",
            "flow": "browser_oauth",
        }

    async def disconnect(self) -> dict[str, object]:
        """Desconecta usando exclusivamente ``claude auth logout``."""

        self._require_installed()
        result = await self._execute_auth_command(
            ("auth", "logout"),
            self.logout_timeout,
        )
        if result.returncode != 0:
            raise ClaudeAuthCommandError
        return {
            "ok": True,
            "provider": "claude",
            "status": "disconnected",
        }

    def _require_installed(self) -> None:
        if not self._detection().available:
            raise ClaudeNotInstalledError

    async def _execute_auth_command(
        self,
        arguments: Sequence[str],
        timeout: float,
    ) -> CliExecutionResult:
        try:
            return await self.runner.execute(arguments, timeout=timeout)
        except CliUnavailableError as error:
            raise ClaudeNotInstalledError from error
        except CliTimeoutError as error:
            raise ClaudeAuthTimeoutError from error
        except ClaudeAuthError:
            raise
        except Exception as error:
            raise ClaudeAuthCommandError from error

    @staticmethod
    def _parse_status(output: str) -> dict[str, object] | None:
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _safe_auth_method(value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        methods = {
            "claude.ai": "claude.ai",
            "claudeai": "claude.ai",
            "oauth": "claude.ai",
            "api_key": "api_key",
            "apikey": "api_key",
            "console": "console",
            "bedrock": "bedrock",
            "vertex": "vertex",
            "foundry": "foundry",
        }
        return methods.get(normalized, "unknown")

    @staticmethod
    def _safe_api_provider(value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        providers = {
            "firstparty": "first_party",
            "first_party": "first_party",
            "anthropic": "first_party",
            "bedrock": "bedrock",
            "vertex": "vertex",
            "foundry": "foundry",
        }
        return providers.get(normalized, "unknown")

    @staticmethod
    def _safe_entitlement(value: object) -> bool | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        return normalized in {"pro", "max", "team", "enterprise"}

    @staticmethod
    def _status_payload(
        *,
        installed: bool,
        connected: bool | None,
        status: str,
        auth_method: str | None = None,
        api_provider: str | None = None,
        entitled: bool | None = None,
    ) -> dict[str, object]:
        return {
            "provider": "claude",
            "installed": installed,
            "connected": connected,
            "status": status,
            "authMethod": auth_method,
            "apiProvider": api_provider,
            "canConnect": installed and connected is not True,
            "canDisconnect": bool(connected),
            "entitled": entitled,
        }
