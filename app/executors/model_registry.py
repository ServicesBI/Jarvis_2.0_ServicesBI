"""Registro central de profiles estáveis para modelos CLI validados."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock


class ModelProfile(str, Enum):
    MAX = "max"
    PRO = "pro"
    FAST = "fast"


DEFAULT_MODEL_PROFILE = ModelProfile.PRO


@dataclass(frozen=True, slots=True)
class ModelResolution:
    provider: str
    profile: ModelProfile
    model_id: str
    display_name: str
    available: bool = True
    enabled: bool = True
    reason: str = "operational"


class ModelUnavailableError(RuntimeError):
    def __init__(self, provider: str, profile: str, reason: str) -> None:
        super().__init__(f"Profile {provider}/{profile} indisponível: {reason}")
        self.provider = provider
        self.profile = profile
        self.reason = reason


class ModelRegistry:
    def __init__(self, resolutions: tuple[ModelResolution, ...]) -> None:
        self._lock = RLock()
        self._resolutions = {
            (item.provider, item.profile): item for item in resolutions
        }

    @classmethod
    def default(cls) -> "ModelRegistry":
        mappings = {
            "codex": {
                ModelProfile.MAX: ("gpt-5.6-sol", "GPT-5.6 Sol"),
                ModelProfile.PRO: ("gpt-5.6-terra", "GPT-5.6 Terra"),
                ModelProfile.FAST: ("gpt-5.6-luna", "GPT-5.6 Luna"),
            },
            "claude": {
                ModelProfile.MAX: ("opus", "Opus 5"),
                ModelProfile.PRO: ("sonnet", "Sonnet 5"),
                ModelProfile.FAST: ("haiku", "Haiku 4.5"),
            },
        }
        return cls(
            tuple(
                ModelResolution(provider, profile, model_id, display_name)
                for provider, profiles in mappings.items()
                for profile, (model_id, display_name) in profiles.items()
            )
        )

    @staticmethod
    def _profile(value: str | ModelProfile) -> ModelProfile:
        try:
            return value if isinstance(value, ModelProfile) else ModelProfile(str(value).lower())
        except ValueError as error:
            raise ValueError("Profile inválido") from error

    def resolve(self, provider: str, profile: str | ModelProfile) -> ModelResolution:
        normalized_provider = str(provider).strip().lower()
        normalized_profile = self._profile(profile)
        with self._lock:
            resolution = self._resolutions.get((normalized_provider, normalized_profile))
        if resolution is None:
            raise ModelUnavailableError(
                normalized_provider, normalized_profile.value, "profile_unavailable"
            )
        if not resolution.enabled or not resolution.available:
            raise ModelUnavailableError(
                normalized_provider, normalized_profile.value, resolution.reason
            )
        return resolution

    def is_available(self, provider: str, profile: str | ModelProfile) -> bool:
        try:
            self.resolve(provider, profile)
        except (ValueError, ModelUnavailableError):
            return False
        return True

    def set_availability(
        self,
        provider: str,
        profile: str | ModelProfile,
        *,
        available: bool,
        reason: str,
    ) -> None:
        normalized_provider = str(provider).strip().lower()
        normalized_profile = self._profile(profile)
        key = (normalized_provider, normalized_profile)
        with self._lock:
            current = self._resolutions.get(key)
            if current is None:
                raise ModelUnavailableError(
                    normalized_provider, normalized_profile.value, "profile_unavailable"
                )
            self._resolutions[key] = replace(
                current, available=available, reason=reason
            )

    def catalog(self) -> dict[str, dict[str, dict[str, object]]]:
        result: dict[str, dict[str, dict[str, object]]] = {}
        with self._lock:
            values = tuple(self._resolutions.values())
        for item in values:
            status = "online" if item.enabled and item.available else item.reason
            result.setdefault(item.provider, {})[item.profile.value] = {
                "profile": item.profile.value,
                "display_name": item.display_name,
                "available": item.available,
                "enabled": item.enabled,
                "reason": item.reason,
                "status": status,
            }
        return result
