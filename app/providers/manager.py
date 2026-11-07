"""In-memory registry and central runtime snapshots for future providers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Callable

from app.providers.contracts import (
    ConnectableProviderAdapter,
    DisconnectableProviderAdapter,
    ExecutableProviderAdapter,
    ProviderAdapter,
    ProviderDomainError,
    ProviderErrorCode,
    RefreshableProviderAdapter,
    TestableProviderAdapter,
)
from app.providers.models import (
    Capability,
    DisplayStatus,
    ProviderAction,
    ProviderCategory,
    ProviderDefinition,
    ProviderRuntimeState,
    derive_display_status,
)


Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """Immutable, public view of one provider without credential material."""

    definition: ProviderDefinition
    runtime_state: ProviderRuntimeState
    display_status: DisplayStatus
    available_actions: tuple[ProviderAction, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "definition": self.definition.to_dict(),
            "runtime_state": self.runtime_state.to_dict(),
            "display_status": self.display_status.value,
            "available_actions": [action.value for action in self.available_actions],
        }


class ProviderManager:
    """Central provider registry with dependency-injected, in-memory state."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._definitions: dict[str, ProviderDefinition] = {}
        self._adapters: dict[str, ProviderAdapter] = {}
        self._states: dict[str, ProviderRuntimeState] = {}
        self._lock = RLock()
        self._refresh_lock = asyncio.Lock()

    def register_definition(self, definition: ProviderDefinition) -> ProviderDefinition:
        if not isinstance(definition, ProviderDefinition):
            raise self._operation_error("Invalid provider definition.")
        with self._lock:
            if definition.id in self._definitions:
                raise self._operation_error("Provider is already registered.")
            self._definitions[definition.id] = definition
            self._states[definition.id] = ProviderRuntimeState(
                provider_id=definition.id,
                automatic_allowed=definition.automatic_allowed_default,
            )
        return definition

    def get_definition(self, provider_id: str) -> ProviderDefinition:
        with self._lock:
            definition = self._definitions.get(provider_id)
        if definition is None:
            raise self._not_found(provider_id)
        return definition

    def list_definitions(
        self,
        *,
        category: ProviderCategory | None = None,
        capability: Capability | None = None,
    ) -> tuple[ProviderDefinition, ...]:
        if category is not None and not isinstance(category, ProviderCategory):
            raise TypeError("category must be ProviderCategory")
        if capability is not None and not isinstance(capability, Capability):
            raise TypeError("capability must be Capability")
        with self._lock:
            definitions = tuple(self._definitions.values())
        return tuple(
            sorted(
                (
                    definition
                    for definition in definitions
                    if (category is None or definition.category is category)
                    and (capability is None or definition.supports(capability))
                ),
                key=lambda definition: definition.id,
            )
        )

    def register_adapter(
        self,
        provider_id: str,
        adapter: object,
        *,
        replace: bool = False,
    ) -> None:
        definition = self.get_definition(provider_id)
        if not isinstance(adapter, ProviderAdapter):
            raise self._operation_error("Adapter does not satisfy ProviderAdapter.")
        if adapter.definition != definition:
            raise self._operation_error("Adapter definition does not match provider.")
        try:
            capabilities = adapter.describe_capabilities()
        except Exception as error:
            raise self._operation_error("Adapter capabilities could not be described.") from error
        if capabilities != definition.capabilities:
            raise self._operation_error("Adapter capabilities do not match provider.")

        with self._lock:
            if provider_id in self._adapters and not replace:
                raise self._operation_error("Adapter is already registered.")
            self._adapters[provider_id] = adapter

    def supports_capability(self, provider_id: str, capability: Capability) -> bool:
        return self.get_definition(provider_id).supports(capability)

    def require_capability(self, provider_id: str, capability: Capability) -> None:
        if not self.supports_capability(provider_id, capability):
            raise ProviderDomainError(
                ProviderErrorCode.CAPABILITY_NOT_SUPPORTED,
                "Provider does not support the requested capability.",
            )

    def get_snapshot(self, provider_id: str) -> ProviderSnapshot:
        definition = self.get_definition(provider_id)
        with self._lock:
            state = self._states[provider_id]
            adapter = self._adapters.get(provider_id)
        return self._snapshot(definition, state, adapter)

    def list_snapshots(self) -> tuple[ProviderSnapshot, ...]:
        return tuple(
            self.get_snapshot(definition.id)
            for definition in self.list_definitions()
        )

    def set_automatic_allowed(
        self, provider_id: str, allowed: bool
    ) -> ProviderSnapshot:
        if not isinstance(allowed, bool):
            raise TypeError("allowed must be bool")
        self.get_definition(provider_id)
        with self._lock:
            self._states[provider_id] = replace(
                self._states[provider_id], automatic_allowed=allowed
            )
        return self.get_snapshot(provider_id)

    async def refresh_provider(self, provider_id: str) -> ProviderSnapshot:
        async with self._refresh_lock:
            return await self._refresh_provider(provider_id)

    async def refresh_all(self) -> tuple[ProviderSnapshot, ...]:
        async with self._refresh_lock:
            snapshots = []
            for definition in self.list_definitions():
                snapshots.append(await self._refresh_provider(definition.id))
            return tuple(snapshots)

    async def _refresh_provider(self, provider_id: str) -> ProviderSnapshot:
        self.get_definition(provider_id)
        with self._lock:
            adapter = self._adapters.get(provider_id)
        if adapter is None:
            return self.get_snapshot(provider_id)

        try:
            state = await adapter.status()
        except Exception:
            self._record_status_failure(
                provider_id,
                code="status_check_failed",
                message="Provider status check failed.",
            )
            return self.get_snapshot(provider_id)

        if not isinstance(state, ProviderRuntimeState) or state.provider_id != provider_id:
            self._record_status_failure(
                provider_id,
                code="invalid_status_result",
                message="Provider status check returned an invalid result.",
            )
            return self.get_snapshot(provider_id)

        with self._lock:
            automatic_allowed = self._states[provider_id].automatic_allowed
            self._states[provider_id] = replace(
                state,
                automatic_allowed=automatic_allowed,
                checked_at=self._now(),
            )
        return self.get_snapshot(provider_id)

    def record_success(self, provider_id: str) -> ProviderSnapshot:
        self.get_definition(provider_id)
        with self._lock:
            current = self._states[provider_id]
            self._states[provider_id] = ProviderRuntimeState(
                provider_id=provider_id,
                installed=True,
                configured=True,
                authenticated=True,
                reachable=True,
                operational=True,
                automatic_allowed=current.automatic_allowed,
                checked_at=self._now(),
            )
        return self.get_snapshot(provider_id)

    def record_failure(
        self, provider_id: str, error: BaseException
    ) -> ProviderSnapshot:
        if not isinstance(error, BaseException):
            raise TypeError("error must be an exception")
        self.get_definition(provider_id)
        self._record_status_failure(
            provider_id,
            code="operation_failed",
            message="Provider operation failed.",
        )
        return self.get_snapshot(provider_id)

    def _record_status_failure(self, provider_id: str, *, code: str, message: str) -> None:
        with self._lock:
            current = self._states[provider_id]
            self._states[provider_id] = replace(
                current,
                reachable=False,
                operational=False,
                checking=False,
                checked_at=self._now(),
                last_error_code=code,
                last_error_message=message,
            )

    def _snapshot(
        self,
        definition: ProviderDefinition,
        state: ProviderRuntimeState,
        adapter: ProviderAdapter | None,
    ) -> ProviderSnapshot:
        return ProviderSnapshot(
            definition=definition,
            runtime_state=state,
            display_status=derive_display_status(state, now=self._now()),
            available_actions=self._available_actions(definition, state, adapter),
        )

    @staticmethod
    def _available_actions(
        definition: ProviderDefinition,
        state: ProviderRuntimeState,
        adapter: ProviderAdapter | None,
    ) -> tuple[ProviderAction, ...]:
        if adapter is None:
            return ()
        supported = {
            ProviderAction.STATUS: isinstance(adapter, ProviderAdapter),
            ProviderAction.CONNECT: (
                isinstance(adapter, ConnectableProviderAdapter)
                and not state.authenticated
            ),
            ProviderAction.DISCONNECT: (
                isinstance(adapter, DisconnectableProviderAdapter)
                and state.authenticated
            ),
            ProviderAction.TEST: (
                isinstance(adapter, TestableProviderAdapter) and state.configured
            ),
            ProviderAction.REFRESH: (
                isinstance(adapter, RefreshableProviderAdapter)
                and state.authenticated
            ),
            ProviderAction.EXECUTE: (
                isinstance(adapter, ExecutableProviderAdapter) and state.operational
            ),
        }
        declared = set(definition.actions)
        return tuple(
            action
            for action in ProviderAction
            if action in declared and supported[action]
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _not_found(provider_id: str) -> ProviderDomainError:
        return ProviderDomainError(
            ProviderErrorCode.PROVIDER_NOT_FOUND,
            f"Provider is not registered: {provider_id}",
        )

    @staticmethod
    def _operation_error(message: str) -> ProviderDomainError:
        return ProviderDomainError(ProviderErrorCode.OPERATION_FAILED, message)
