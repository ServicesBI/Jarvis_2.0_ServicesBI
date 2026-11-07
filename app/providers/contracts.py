"""Adapter interfaces and domain errors for future provider integrations."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from app.providers.models import Capability, ProviderDefinition, ProviderRuntimeState


class ProviderErrorCode(str, Enum):
    PROVIDER_NOT_FOUND = "provider_not_found"
    CAPABILITY_NOT_SUPPORTED = "capability_not_supported"
    NOT_CONFIGURED = "not_configured"
    NOT_AUTHENTICATED = "not_authenticated"
    CREDENTIAL_EXPIRED = "credential_expired"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    OPERATION_FAILED = "operation_failed"


class ProviderDomainError(RuntimeError):
    """Single domain exception distinguished by a stable, serializable code."""

    def __init__(self, code: ProviderErrorCode, message: str) -> None:
        if not isinstance(code, ProviderErrorCode):
            raise TypeError("code must be ProviderErrorCode")
        super().__init__(message)
        self.code = code


@runtime_checkable
class ProviderAdapter(Protocol):
    """Operations common to every provider adapter."""

    definition: ProviderDefinition

    async def status(self) -> ProviderRuntimeState: ...

    def describe_capabilities(self) -> tuple[Capability, ...]: ...


@runtime_checkable
class ConnectableProviderAdapter(ProviderAdapter, Protocol):
    async def connect(self) -> ProviderRuntimeState: ...


@runtime_checkable
class DisconnectableProviderAdapter(ProviderAdapter, Protocol):
    async def disconnect(self) -> ProviderRuntimeState: ...


@runtime_checkable
class TestableProviderAdapter(ProviderAdapter, Protocol):
    async def test_capability(self, capability: Capability) -> ProviderRuntimeState: ...


@runtime_checkable
class RefreshableProviderAdapter(ProviderAdapter, Protocol):
    async def refresh_auth(self) -> ProviderRuntimeState: ...


@runtime_checkable
class ExecutableProviderAdapter(ProviderAdapter, Protocol):
    async def execute(
        self, capability: Capability, payload: Mapping[str, Any]
    ) -> Any: ...
