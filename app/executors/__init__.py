"""Infraestrutura desacoplada para executores locais do JARVIS."""

from app.executors.availability import (
    AUTO_PROVIDER_PRIORITY,
    ProviderAvailability,
    ProviderAvailabilityService,
)
from app.executors.cli import AsyncCliExecutor, CliDetection, CliExecutionResult
from app.executors.claude_auth import ClaudeAuthService
from app.executors.codex_auth import CodexAuthService
from app.executors.service import VALID_EXECUTOR_MODES, ExecutorService, executor_service

__all__ = [
    "AUTO_PROVIDER_PRIORITY",
    "AsyncCliExecutor",
    "CliDetection",
    "CliExecutionResult",
    "ClaudeAuthService",
    "CodexAuthService",
    "ExecutorService",
    "ProviderAvailability",
    "ProviderAvailabilityService",
    "VALID_EXECUTOR_MODES",
    "executor_service",
]
