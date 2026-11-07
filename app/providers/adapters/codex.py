"""Thin ProviderManager adapter over the existing Codex services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.executors.availability import ProviderAvailabilityService
from app.providers.contracts import ProviderDomainError, ProviderErrorCode
from app.providers.models import Capability, ProviderDefinition, ProviderRuntimeState


class CodexAuth(Protocol):
    async def status(self) -> dict[str, object]: ...

    async def connect(self) -> dict[str, object]: ...

    async def disconnect(self) -> dict[str, object]: ...


class CodexProviderAdapter:
    """Maps existing Codex auth and execution services into provider contracts."""

    def __init__(
        self,
        *,
        definition: ProviderDefinition,
        auth_service: CodexAuth,
        executor: ChatExecutor,
        availability: ProviderAvailabilityService,
    ) -> None:
        if definition.id != "codex":
            raise ValueError("Codex adapter requires the codex definition")
        self.definition = definition
        self.auth_service = auth_service
        self.executor = executor
        self.availability = availability

    async def status(self) -> ProviderRuntimeState:
        try:
            payload = await self.auth_service.status()
        except Exception:
            return self._error_state("status_failed", "Codex status check failed.")

        installed = payload.get("installed") is True
        connected = payload.get("connected") is True
        status = payload.get("status")
        error_code = payload.get("errorCode")

        if not installed:
            return ProviderRuntimeState(
                provider_id=self.definition.id,
                last_error_code="not_installed",
                last_error_message="Codex CLI is not installed.",
            )
        if status == "timeout" or error_code == "status_timeout":
            return self._error_state(
                "status_timeout",
                "Codex status check timed out.",
                installed=True,
                configured=True,
            )
        if status in {"error", "unknown"} or error_code == "status_failed":
            return self._error_state(
                "status_failed",
                "Codex status check failed.",
                installed=True,
                configured=True,
            )

        operational_evidence = self.availability.get_state("codex").operational
        return ProviderRuntimeState(
            provider_id=self.definition.id,
            installed=True,
            configured=True,
            authenticated=connected,
            reachable=True,
            operational=connected and operational_evidence,
        )

    async def connect(self) -> ProviderRuntimeState:
        await self.auth_service.connect()
        return await self.status()

    async def disconnect(self) -> ProviderRuntimeState:
        await self.auth_service.disconnect()
        return await self.status()

    async def execute(
        self,
        capability: Capability,
        payload: Mapping[str, Any],
    ) -> str:
        if capability not in self.definition.capabilities:
            raise ProviderDomainError(
                ProviderErrorCode.CAPABILITY_NOT_SUPPORTED,
                "Provider does not support the requested capability.",
            )
        message = payload.get("message") if isinstance(payload, Mapping) else None
        if not isinstance(message, str) or not message:
            raise ProviderDomainError(
                ProviderErrorCode.OPERATION_FAILED,
                "Codex request is invalid.",
            )
        chunks = []
        async for chunk in self.executor.stream(ChatRequest(message)):
            chunks.append(chunk)
        return "".join(chunks)

    def describe_capabilities(self) -> tuple[Capability, ...]:
        return self.definition.capabilities

    def _error_state(
        self,
        code: str,
        message: str,
        *,
        installed: bool = False,
        configured: bool = False,
    ) -> ProviderRuntimeState:
        return ProviderRuntimeState(
            provider_id=self.definition.id,
            installed=installed,
            configured=configured,
            authenticated=False,
            reachable=False,
            operational=False,
            last_error_code=code,
            last_error_message=message,
        )
