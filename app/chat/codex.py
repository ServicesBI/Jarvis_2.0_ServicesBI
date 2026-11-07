"""Adaptador do Codex CLI para o contrato de streaming do chat."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.executors.cli import CliExecutionResult
from app.executors.model_registry import ModelResolution


class CliRunner(Protocol):
    async def execute(
        self,
        arguments: Sequence[str] = (),
        *,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        stdin_text: str | None = None,
    ) -> CliExecutionResult: ...


class CodexProcessError(RuntimeError):
    """Falha do Codex preservando stdout/stderr para diagnóstico interno."""

    def __init__(self, result: CliExecutionResult) -> None:
        detail = (
            f"Codex CLI encerrou com código {result.returncode}"
            if result.returncode != 0
            else "Codex CLI não retornou saída"
        )
        super().__init__(detail)
        self.returncode = result.returncode
        self.stdout = result.stdout
        self.stderr = result.stderr


class CodexChatExecutor(ChatExecutor):
    """Executa somente respostas textuais em sandbox read-only."""

    def __init__(
        self,
        runner: CliRunner,
        *,
        cwd: Path,
        timeout: float = 90.0,
        model_resolver=None,
    ) -> None:
        self.runner = runner
        self.cwd = cwd
        self.timeout = timeout
        self.model_resolver = model_resolver

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        resolution: ModelResolution | None = (
            self.model_resolver() if self.model_resolver is not None else None
        )
        arguments = (
            *(("-m", resolution.model_id) if resolution is not None else ()),
            "--ask-for-approval",
            "never",
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-C",
            str(self.cwd),
            "-",
        )
        result = await self.runner.execute(
            arguments,
            timeout=self.timeout,
            cwd=self.cwd,
            stdin_text=request.message,
        )
        if result.returncode != 0 or not result.stdout:
            raise CodexProcessError(result)
        yield result.stdout
