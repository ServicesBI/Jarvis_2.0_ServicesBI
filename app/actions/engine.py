"""Orquestra validação e execução de ações pelo TaskManager oficial."""

from __future__ import annotations

from typing import Any

from app.actions.models import ActionRequest, ActionResult
from app.actions.policy import ActionPolicy
from app.actions.registry import ActionRegistry
from app.tasks.manager import TaskManager


class ActionVerificationError(RuntimeError):
    """O handler terminou, mas o efeito declarado não foi comprovado."""


class ActionEngine:
    def __init__(
        self,
        registry: ActionRegistry,
        task_manager: TaskManager,
        policy: ActionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.task_manager = task_manager
        self.policy = policy or ActionPolicy()

    def submit(self, request: ActionRequest) -> dict[str, Any]:
        definition = self.registry.resolve(request.action, source=request.source)
        arguments = self.registry.validate_arguments(
            definition.name, request.arguments
        )
        self.policy.authorize(definition, request)

        async def operation() -> dict[str, Any]:
            raw_result = await definition.handler(arguments)
            result = (
                raw_result
                if isinstance(raw_result, ActionResult)
                else ActionResult.model_validate(raw_result)
            )
            result = result.model_copy(update={"action": definition.name})
            if not result.ok:
                raise RuntimeError(result.error or "Handler não confirmou sucesso.")
            if definition.verifier is not None:
                verified = await definition.verifier(arguments, result)
                if not verified:
                    raise ActionVerificationError(
                        f"Verifier não comprovou o efeito de {definition.name}."
                    )
            return self.policy.persistent_result(result, definition.persistence)

        return self.task_manager.submit(
            definition.name,
            definition.description,
            operation,
            timeout=definition.timeout,
            desktop_exclusive=definition.desktop_exclusive,
            executor="local",
            display_name=str(getattr(arguments, "name", None) or getattr(arguments, "filename", None) or definition.description),
        )
