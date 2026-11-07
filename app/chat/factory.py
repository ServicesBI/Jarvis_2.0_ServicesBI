"""Composição da camada de chat com o gerenciador de executores."""

from app.chat.claude import CliRunner as ClaudeCliRunner
from app.chat.claude import ClaudeChatExecutor
from app.chat.codex import CliRunner as CodexCliRunner
from app.chat.codex import CodexChatExecutor
from app.chat.executor import (
    AutoChatExecutor,
    AvailabilityObservedExecutor,
    ChatExecutor,
    ModeAwareChatExecutor,
    NoEligibleProviderExecutor,
    UnavailableChatExecutor,
)
from app.chat.service import ChatService
from app.core.config import PROJECT_ROOT
from app.executors.availability import ProviderAvailabilityService
from app.executors.cli import AsyncCliExecutor
from app.executors.service import ExecutorService
from app.providers.manager import ProviderManager


def create_managed_chat_service(
    executor_manager: ExecutorService,
    codex_runner: CodexCliRunner | None = None,
    claude_runner: ClaudeCliRunner | None = None,
    availability: ProviderAvailabilityService | None = None,
    openai_executor: ChatExecutor | None = None,
    provider_manager: ProviderManager | None = None,
    task_manager=None,
) -> ChatService:
    """Monta o chat sem detectar ou executar CLIs durante a inicialização."""

    codex = (
        codex_runner
        if codex_runner is not None
        else AsyncCliExecutor(
            executor_manager.get_command("codex"),
            default_timeout=90.0,
        )
    )
    claude = (
        claude_runner
        if claude_runner is not None
        else AsyncCliExecutor(
            executor_manager.get_command("claude"),
            default_timeout=90.0,
        )
    )
    availability_service = availability or ProviderAvailabilityService()
    provider_executors: dict[str, ChatExecutor] = {
        "codex": AvailabilityObservedExecutor(
            "codex",
            CodexChatExecutor(
                codex,
                cwd=PROJECT_ROOT,
                timeout=90.0,
                model_resolver=lambda: executor_manager.resolve_model("codex"),
            ),
            availability_service,
            None,
            task_manager,
        ),
        "claude": AvailabilityObservedExecutor(
            "claude",
            ClaudeChatExecutor(
                claude,
                cwd=PROJECT_ROOT,
                timeout=90.0,
                model_resolver=lambda: executor_manager.resolve_model("claude"),
            ),
            availability_service,
            None,
            task_manager,
        ),
    }
    if openai_executor is not None:
        provider_executors["openai"] = AvailabilityObservedExecutor(
            "openai",
            openai_executor,
            availability_service,
            provider_manager,
            task_manager,
        )

    auto_executor = AutoChatExecutor(
        provider_executors,
        availability_service,
        NoEligibleProviderExecutor(),
        model_available=lambda provider: executor_manager.model_registry.is_available(
            provider, executor_manager.get_profile(provider)
        ),
    )
    selected_executor = ModeAwareChatExecutor(
        executor_manager.get_mode,
        {**provider_executors, "auto": auto_executor},
        UnavailableChatExecutor(),
        availability_service,
    )
    return ChatService(selected_executor)
