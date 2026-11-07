"""Detecção passiva e base assíncrona para executores CLI."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CliDetection:
    """Resultado de uma consulta passiva ao PATH, sem iniciar processos."""

    provider: str
    command: str
    available: bool
    path: str | None = None


@dataclass(frozen=True)
class CliExecutionResult:
    """Saída capturada de uma futura execução CLI."""

    returncode: int
    stdout: str
    stderr: str


class CliUnavailableError(RuntimeError):
    """O executável solicitado não existe ou não pode ser iniciado."""


class CliTimeoutError(TimeoutError):
    """O processo excedeu o tempo limite e foi encerrado."""

    def __init__(self, timeout: float, stdout: str = "", stderr: str = "") -> None:
        super().__init__(f"CLI excedeu o timeout de {timeout:g}s")
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


def detect_cli(provider: str, command: str) -> CliDetection:
    """Localiza um comando sem executar --version, --help ou autenticação."""

    normalized_command = command.strip()
    if not normalized_command:
        return CliDetection(provider=provider, command=command, available=False)
    resolved_path = shutil.which(normalized_command)
    return CliDetection(
        provider=provider,
        command=normalized_command,
        available=resolved_path is not None,
        path=str(Path(resolved_path)) if resolved_path else None,
    )


class AsyncCliExecutor:
    """Base sem shell para a futura execução de Claude e Codex.

    Nenhuma instância inicia processos durante importação ou detecção. A chamada
    explícita a ``execute`` usa ``asyncio.create_subprocess_exec`` e garante
    encerramento em timeout ou cancelamento da coroutine.
    """

    def __init__(
        self,
        command: str,
        *,
        default_timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if default_timeout <= 0:
            raise ValueError("default_timeout deve ser maior que zero")
        self.command = command
        self.default_timeout = default_timeout
        self.environment = dict(environment) if environment is not None else None

    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult:
        effective_timeout = self.default_timeout if timeout is None else timeout
        if effective_timeout <= 0:
            raise ValueError("timeout deve ser maior que zero")

        try:
            process = await asyncio.create_subprocess_exec(
                self.command,
                *arguments,
                cwd=str(cwd) if cwd is not None else None,
                stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=(
                    {**os.environ, **self.environment}
                    if self.environment is not None
                    else None
                ),
            )
        except (FileNotFoundError, PermissionError, OSError) as error:
            raise CliUnavailableError(f"CLI indisponível: {self.command}") from error

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(
                    stdin_text.encode("utf-8") if stdin_text is not None else None
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError as error:
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            raise CliTimeoutError(
                effective_timeout,
                self._decode(stdout_bytes),
                self._decode(stderr_bytes),
            ) from error
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await asyncio.shield(process.communicate())
            raise

        return CliExecutionResult(
            returncode=process.returncode,
            stdout=self._decode(stdout_bytes),
            stderr=self._decode(stderr_bytes),
        )

    @staticmethod
    def _decode(output: bytes | None) -> str:
        return (output or b"").decode("utf-8", errors="replace")
