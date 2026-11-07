"""Autenticação oficial do Codex CLI sem manipular credenciais diretamente."""

from __future__ import annotations

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


class CodexAuthError(RuntimeError):
    """Erro público controlado de uma operação de autenticação."""


class CodexNotInstalledError(CodexAuthError):
    """O Codex CLI não está disponível no PATH configurado."""


class CodexAuthTimeoutError(CodexAuthError):
    """O fluxo oficial não terminou dentro do limite configurado."""


class CodexAuthCommandError(CodexAuthError):
    """O comando oficial terminou sem sucesso."""


class CodexAuthUnsupportedError(CodexAuthError):
    """O ambiente escolheu um método que não aceita login/logout local."""


Detector = Callable[[str, str], CliDetection]


class CodexAuthService:
    """Executa somente os comandos oficiais login/status/logout do Codex."""

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
        return self.detector("Codex", self.command)

    async def status(self) -> dict[str, object]:
        """Retorna somente estado sanitizado; nunca stdout, stderr ou tokens."""

        if not self._detection().available:
            return self._status_payload(
                installed=False,
                connected=False,
                status="not_installed",
            )

        try:
            result = await self.runner.execute(
                ("login", "status"),
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
                status="timeout",
                error_code="status_timeout",
            )
        except Exception:
            return self._status_payload(
                installed=True,
                connected=None,
                status="error",
                error_code="status_failed",
            )

        if result.returncode != 0:
            return self._status_payload(
                installed=True,
                connected=False,
                status="disconnected",
            )

        auth_method = self._auth_method(result)
        workload_identity = auth_method == "workload_identity"
        return self._status_payload(
            installed=True,
            connected=True,
            status="connected",
            auth_method=auth_method,
            can_connect=False,
            can_disconnect=not workload_identity,
        )

    async def connect(self) -> dict[str, object]:
        """Inicia o OAuth oficial do ChatGPT por ``codex login``."""

        self._require_installed()
        result = await self._execute_auth_command(("login",), self.login_timeout)
        if result.returncode != 0:
            if self._is_workload_identity(result):
                raise CodexAuthUnsupportedError
            raise CodexAuthCommandError
        return {
            "ok": True,
            "provider": "codex",
            "status": "connected",
            "authMethod": "chatgpt",
            "flow": "browser_oauth",
        }

    async def disconnect(self) -> dict[str, object]:
        """Remove credenciais armazenadas usando somente ``codex logout``."""

        self._require_installed()
        result = await self._execute_auth_command(("logout",), self.logout_timeout)
        if result.returncode != 0:
            if self._is_workload_identity(result):
                raise CodexAuthUnsupportedError
            raise CodexAuthCommandError
        return {
            "ok": True,
            "provider": "codex",
            "status": "disconnected",
        }

    def _require_installed(self) -> None:
        if not self._detection().available:
            raise CodexNotInstalledError

    async def _execute_auth_command(
        self,
        arguments: Sequence[str],
        timeout: float,
    ) -> CliExecutionResult:
        try:
            return await self.runner.execute(arguments, timeout=timeout)
        except CliUnavailableError as error:
            raise CodexNotInstalledError from error
        except CliTimeoutError as error:
            raise CodexAuthTimeoutError from error
        except CodexAuthError:
            raise
        except Exception as error:
            raise CodexAuthCommandError from error

    @staticmethod
    def _auth_method(result: CliExecutionResult) -> str:
        output = f"{result.stdout}\n{result.stderr}".lower()
        if "workload identity" in output:
            return "workload_identity"
        if "access token" in output:
            return "access_token"
        if "api key" in output or "api_key" in output:
            return "api_key"
        if "chatgpt" in output or "oauth" in output:
            return "chatgpt"
        return "unknown"

    @staticmethod
    def _is_workload_identity(result: CliExecutionResult) -> bool:
        return "workload identity" in f"{result.stdout}\n{result.stderr}".lower()

    @staticmethod
    def _status_payload(
        *,
        installed: bool,
        connected: bool | None,
        status: str,
        auth_method: str | None = None,
        can_connect: bool | None = None,
        can_disconnect: bool | None = None,
        error_code: str | None = None,
    ) -> dict[str, object]:
        resolved_can_connect = (
            installed and connected is not True
            if can_connect is None
            else can_connect
        )
        resolved_can_disconnect = (
            bool(connected) if can_disconnect is None else can_disconnect
        )
        payload: dict[str, object] = {
            "provider": "codex",
            "installed": installed,
            "connected": connected,
            "status": status,
            "authMethod": auth_method,
            "canConnect": resolved_can_connect,
            "canDisconnect": resolved_can_disconnect,
        }
        if error_code is not None:
            payload["errorCode"] = error_code
        return payload
