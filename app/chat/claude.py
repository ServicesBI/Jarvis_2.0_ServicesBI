"""Adaptador do Claude Code CLI para o contrato de streaming do chat."""

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


class ClaudeProcessError(RuntimeError):
    """Falha do Claude preservando stdout/stderr apenas internamente."""

    def __init__(self, result: CliExecutionResult) -> None:
        detail = (
            f"Claude Code CLI encerrou com código {result.returncode}"
            if result.returncode != 0
            else "Claude Code CLI não retornou saída"
        )
        super().__init__(detail)
        self.returncode = result.returncode
        self.stdout = result.stdout
        self.stderr = result.stderr


class ClaudeChatExecutor(ChatExecutor):
    """Executa uma resposta textual sem ferramentas ou persistência de sessão."""

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
            *(("--model", resolution.model_id) if resolution is not None else ()),
            "--print",
            "--output-format",
            "text",
            "--safe-mode",
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--no-session-persistence",
        )
        result = await self.runner.execute(
            arguments,
            timeout=self.timeout,
            cwd=self.cwd,
            stdin_text=request.message,
        )
        if result.returncode != 0 or not result.stdout:
            raise ClaudeProcessError(result)
        yield result.stdout
