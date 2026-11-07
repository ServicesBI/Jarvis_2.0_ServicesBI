"""Registry allowlisted de definições de ações do Jarvis."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.actions.models import ActionResult, ActionRisk, PersistencePolicy


ActionHandler = Callable[[BaseModel], Awaitable[ActionResult | dict[str, object]]]
ActionVerifier = Callable[[BaseModel, ActionResult], Awaitable[bool]]
ACTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class ActionRegistryError(ValueError):
    pass


class DuplicateActionError(ActionRegistryError):
    pass


class UnknownActionError(ActionRegistryError):
    pass


class ActionNotAllowedError(PermissionError):
    pass


class UnsafeActionError(ActionRegistryError):
    pass


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ActionHandler
    verifier: ActionVerifier | None
    risk: ActionRisk
    confirmation_required: bool
    timeout: float
    desktop_exclusive: bool
    persistence: PersistencePolicy
    allowed_sources: frozenset[str]
    requires_verification: bool = True

    def __post_init__(self) -> None:
        normalized_name = self.name.strip().lower()
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(
            self,
            "allowed_sources",
            frozenset(source.strip().lower() for source in self.allowed_sources),
        )
        if "shell" in normalized_name.split("."):
            raise UnsafeActionError("Ação shell não pode ser definida.")
        if not ACTION_NAME_PATTERN.fullmatch(normalized_name):
            raise ValueError("Nome de ação inválido; use o formato família.ação.")
        if self.timeout <= 0:
            raise ValueError("Timeout da ação deve ser positivo.")
        if not self.allowed_sources:
            raise ValueError("A ação deve permitir ao menos uma origem.")
        if self.requires_verification and self.verifier is None:
            raise ValueError("Ação com efeito verificável exige verifier.")


class ActionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ActionDefinition] = {}

    @staticmethod
    def _reject_unsafe_name(name: str) -> None:
        if "shell" in name.strip().lower().split("."):
            raise UnsafeActionError("Ação shell não pode ser registrada.")

    def register(self, definition: ActionDefinition) -> ActionDefinition:
        self._reject_unsafe_name(definition.name)
        if definition.name in self._definitions:
            raise DuplicateActionError(f"Ação já registrada: {definition.name}")
        self._definitions[definition.name] = definition
        return definition

    def resolve(self, name: str, *, source: str) -> ActionDefinition:
        normalized_name = name.strip().lower()
        self._reject_unsafe_name(normalized_name)
        definition = self._definitions.get(normalized_name)
        if definition is None:
            raise UnknownActionError(f"Ação desconhecida: {normalized_name}")
        normalized_source = source.strip().lower()
        if normalized_source not in definition.allowed_sources:
            raise ActionNotAllowedError(
                f"Ação {normalized_name} não permitida para origem {normalized_source}."
            )
        return definition

    def validate_arguments(self, name: str, arguments: object) -> BaseModel:
        normalized_name = name.strip().lower()
        definition = self._definitions.get(normalized_name)
        if definition is None:
            raise UnknownActionError(f"Ação desconhecida: {normalized_name}")
        return definition.input_model.model_validate(arguments)

    def definitions_for(self, source: str) -> tuple[ActionDefinition, ...]:
        normalized_source = source.strip().lower()
        return tuple(
            definition
            for definition in self._definitions.values()
            if normalized_source in definition.allowed_sources
        )
