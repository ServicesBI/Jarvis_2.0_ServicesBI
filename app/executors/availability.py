"""Estado central de disponibilidade e elegibilidade dos provedores."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from threading import RLock

from app.executors.cli import CliTimeoutError, CliUnavailableError


AUTO_PROVIDER_PRIORITY = ("codex", "claude")
SUPPORTED_PROVIDERS = frozenset((*AUTO_PROVIDER_PRIORITY, "openai"))


@dataclass(frozen=True)
class ProviderAvailability:
    provider: str
    installed: bool = False
    authenticated: bool = False
    operational: bool = False
    automatic_allowed: bool = True
    reason: str = "not_evaluated"
    entitled: bool | None = None

    @property
    def eligible(self) -> bool:
        return (
            self.installed
            and self.authenticated
            and self.operational
            and self.automatic_allowed
        )

    @property
    def lazy_eligible(self) -> bool:
        return (
            self.installed
            and self.authenticated
            and self.entitled is True
            and not self.operational
            and self.automatic_allowed
            and self.reason == "capability_not_validated"
        )

    @property
    def status(self) -> str:
        if not self.installed:
            return "offline"
        if not self.authenticated:
            return "not_authenticated"
        if not self.operational:
            if self.reason == "plan_unavailable":
                return "entitlement_unavailable"
            return "unknown"
        return "online"

    def health_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "installed": self.installed,
            "connected": self.authenticated,
            "authenticated": self.authenticated,
            "operational": self.operational,
            "eligible": self.eligible,
            "automatic_allowed": self.automatic_allowed,
            "entitled": self.entitled,
            "reason": self.reason,
        }


StatusProbe = Callable[[], Awaitable[Mapping[str, object]]]


@dataclass(frozen=True)
class _ProbeRegistration:
    probe: StatusProbe
    authentication_implies_operational: bool


class ProviderAvailabilityService:
    """Mantém estados reais sem executar provedores durante o startup."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._states = {
            provider: ProviderAvailability(provider=provider)
            for provider in SUPPORTED_PROVIDERS
        }
        self._probes: dict[str, _ProbeRegistration] = {}

    def register_status_probe(
        self,
        provider: str,
        probe: StatusProbe,
        *,
        authentication_implies_operational: bool,
    ) -> None:
        self._require_provider(provider)
        with self._lock:
            self._probes[provider] = _ProbeRegistration(
                probe=probe,
                authentication_implies_operational=authentication_implies_operational,
            )

    def set_state(
        self,
        provider: str,
        *,
        installed: bool,
        authenticated: bool,
        operational: bool,
        automatic_allowed: bool = True,
        reason: str = "configured",
        entitled: bool | None = None,
    ) -> ProviderAvailability:
        self._require_provider(provider)
        state = ProviderAvailability(
            provider=provider,
            installed=installed,
            authenticated=authenticated,
            operational=operational,
            automatic_allowed=automatic_allowed,
            reason=reason,
            entitled=entitled,
        )
        with self._lock:
            self._states[provider] = state
        return state

    def get_state(self, provider: str) -> ProviderAvailability:
        self._require_provider(provider)
        with self._lock:
            return self._states[provider]

    def eligible_providers(
        self,
        implemented_providers: Iterable[str],
    ) -> tuple[str, ...]:
        implemented = set(implemented_providers)
        with self._lock:
            return tuple(
                provider
                for provider in AUTO_PROVIDER_PRIORITY
                if provider in implemented
                and (
                    self._states[provider].eligible
                    or self._states[provider].lazy_eligible
                )
            )

    def can_attempt(self, provider: str, *, automatic: bool) -> bool:
        state = self.get_state(provider)
        if state.reason == "not_evaluated":
            return True
        if not state.installed or not state.authenticated:
            return False
        if automatic and not state.automatic_allowed:
            return False
        return state.operational or (
            state.entitled is True and state.reason == "capability_not_validated"
        )

    async def refresh(self) -> None:
        """Executa apenas probes oficiais registrados, nunca chat/modelo."""

        with self._lock:
            registrations = tuple(self._probes.items())

        if not registrations:
            return

        results = await asyncio.gather(
            *(registration.probe() for _, registration in registrations),
            return_exceptions=True,
        )
        for (provider, registration), result in zip(registrations, results):
            if isinstance(result, BaseException):
                current = self.get_state(provider)
                self.set_state(
                    provider,
                    installed=current.installed,
                    authenticated=current.authenticated,
                    operational=False,
                    automatic_allowed=current.automatic_allowed,
                    reason="status_probe_failed",
                    entitled=current.entitled,
                )
                continue
            self._apply_status_probe(provider, registration, result)

    async def refresh_provider(self, provider: str) -> ProviderAvailability:
        """Atualiza um único provider pela probe registrada, sem executar chat."""

        self._require_provider(provider)
        with self._lock:
            registration = self._probes.get(provider)
        if registration is None:
            return self.get_state(provider)
        try:
            result = await registration.probe()
        except BaseException:
            current = self.get_state(provider)
            return self.set_state(
                provider,
                installed=current.installed,
                authenticated=current.authenticated,
                operational=False,
                automatic_allowed=current.automatic_allowed,
                reason="status_probe_failed",
                entitled=current.entitled,
            )
        self._apply_status_probe(provider, registration, result)
        return self.get_state(provider)

    def record_success(self, provider: str) -> ProviderAvailability:
        current = self.get_state(provider)
        return self.set_state(
            provider,
            installed=True,
            authenticated=True,
            operational=True,
            automatic_allowed=current.automatic_allowed,
            reason="operational",
            entitled=True,
        )

    def record_failure(
        self,
        provider: str,
        error: BaseException,
    ) -> ProviderAvailability:
        current = self.get_state(provider)
        detail = self._error_detail(error)

        if isinstance(error, CliUnavailableError) or any(
            marker in detail
            for marker in ("not found", "não encontrado", "indisponível")
        ):
            return self.set_state(
                provider,
                installed=False,
                authenticated=False,
                operational=False,
                automatic_allowed=current.automatic_allowed,
                reason="not_installed",
                entitled=current.entitled,
            )

        if any(
            marker in detail
            for marker in (
                "401",
                "oauth",
                "access token has expired",
                "failed to authenticate",
                "not authenticated",
                "not logged in",
            )
        ):
            return self.set_state(
                provider,
                installed=True,
                authenticated=False,
                operational=False,
                automatic_allowed=current.automatic_allowed,
                reason="authentication_failed",
                entitled=current.entitled,
            )

        if any(
            marker in detail
            for marker in (
                "plan",
                "subscription",
                "billing",
                "quota",
                "usage limit",
                "credit",
            )
        ):
            return self.set_state(
                provider,
                installed=True,
                authenticated=current.authenticated,
                operational=False,
                automatic_allowed=current.automatic_allowed,
                reason="plan_unavailable",
                entitled=False,
            )

        reason = "timeout" if isinstance(error, CliTimeoutError) else "execution_failed"
        return self.set_state(
            provider,
            installed=current.installed,
            authenticated=current.authenticated,
            operational=False,
            automatic_allowed=current.automatic_allowed,
            reason=reason,
            entitled=current.entitled,
        )

    def _apply_status_probe(
        self,
        provider: str,
        registration: _ProbeRegistration,
        payload: Mapping[str, object],
    ) -> None:
        current = self.get_state(provider)
        installed = payload.get("installed") is True
        authenticated = payload.get("connected") is True
        entitled = payload.get("entitled")
        entitled = entitled if isinstance(entitled, bool) else current.entitled

        if not installed:
            operational = False
            reason = "not_installed"
        elif not authenticated:
            operational = False
            reason = "not_authenticated"
        elif entitled is False:
            operational = False
            reason = "plan_unavailable"
        elif registration.authentication_implies_operational:
            operational = current.reason not in {
                "authentication_failed",
                "plan_unavailable",
            }
            reason = "status_connected" if operational else current.reason
        else:
            operational = current.operational
            reason = current.reason if operational else "capability_not_validated"

        self.set_state(
            provider,
            installed=installed,
            authenticated=authenticated,
            operational=operational,
            automatic_allowed=current.automatic_allowed,
            reason=reason,
            entitled=entitled,
        )

    @staticmethod
    def _error_detail(error: BaseException) -> str:
        parts = [str(error)]
        for attribute in ("stdout", "stderr"):
            value = getattr(error, attribute, None)
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts).lower()

    @staticmethod
    def _require_provider(provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Provedor desconhecido: {provider}")
