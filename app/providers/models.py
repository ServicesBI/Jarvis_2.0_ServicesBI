"""Canonical domain models for providers, identities and connections."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any


_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")


class StableEnum(str, Enum):
    """String enum with values suitable for stable JSON contracts."""


class ProviderCategory(StableEnum):
    AI = "ai"
    CLOUD = "cloud"
    MICROSOFT = "microsoft"
    DEVELOPMENT = "development"
    ERP = "erp"
    SYSTEM = "system"


class AuthMethod(StableEnum):
    CLI_OAUTH = "cli_oauth"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    LOCAL = "local"
    USER_PASSWORD = "user_password"
    CERTIFICATE = "certificate"
    CUSTOM = "custom"


class Capability(StableEnum):
    CHAT = "chat"
    STT = "stt"
    TTS = "tts"
    REALTIME = "realtime"
    VISION = "vision"
    FILES = "files"
    DRIVE = "drive"
    EMAIL = "email"
    CALENDAR = "calendar"
    SHEETS = "sheets"
    BI = "bi"
    CODE = "code"
    LOCAL_TOOL = "local_tool"
    ERP_READ = "erp_read"
    ERP_WRITE = "erp_write"


class AdapterKind(StableEnum):
    PYTHON = "python"
    NODE = "node"
    CLI = "cli"
    LOCAL = "local"
    EXTERNAL = "external"


class ProviderAction(StableEnum):
    STATUS = "status"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    TEST = "test"
    REFRESH = "refresh"
    EXECUTE = "execute"


class DisplayStatus(StableEnum):
    NOT_INSTALLED = "not_installed"
    NOT_CONFIGURED = "not_configured"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    CHECKING = "checking"
    DEGRADED = "degraded"
    ERROR = "error"
    CONNECTED = "connected"
    OPERATIONAL = "operational"


def _validate_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {field_name}")


def _validate_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {field_name}")


def _validate_enum(value: object, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be {enum_type.__name__}")


def _validate_enum_tuple(
    values: tuple[object, ...], enum_type: type[Enum], field_name: str
) -> None:
    if not isinstance(values, tuple) or any(not isinstance(value, enum_type) for value in values):
        raise TypeError(f"{field_name} must contain only {enum_type.__name__}")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


def _validate_optional_datetime(value: datetime | None, field_name: str) -> None:
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
        raise ValueError(f"{field_name} must be timezone-aware")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        normalized = value.astimezone(timezone.utc).isoformat()
        return normalized.replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


class JsonContract:
    """Predictable JSON-ready serialization without credential material."""

    def to_dict(self) -> dict[str, Any]:
        return {
            field.name: _json_value(getattr(self, field.name))
            for field in fields(self)
        }


@dataclass(frozen=True, slots=True)
class ProviderDefinition(JsonContract):
    id: str
    name: str
    category: ProviderCategory
    description: str
    capabilities: tuple[Capability, ...]
    auth_methods: tuple[AuthMethod, ...]
    supports_multiple_accounts: bool
    adapter_kind: AdapterKind
    automatic_allowed_default: bool = True
    actions: tuple[ProviderAction, ...] = (ProviderAction.STATUS,)

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "provider id")
        _validate_text(self.name, "provider name")
        _validate_text(self.description, "provider description")
        _validate_enum(self.category, ProviderCategory, "category")
        _validate_enum(self.adapter_kind, AdapterKind, "adapter_kind")
        _validate_enum_tuple(self.capabilities, Capability, "capabilities")
        _validate_enum_tuple(self.auth_methods, AuthMethod, "auth_methods")
        _validate_enum_tuple(self.actions, ProviderAction, "actions")

    def supports(self, capability: Capability) -> bool:
        _validate_enum(capability, Capability, "capability")
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class ProviderIdentity(JsonContract):
    identity_id: str
    provider_id: str
    display_name: str
    created_at: datetime
    updated_at: datetime
    account_hint: str | None = None
    tenant_hint: str | None = None
    scopes: tuple[str, ...] = ()
    credential_ref: str | None = None
    expires_at: datetime | None = None
    last_checked_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.identity_id, "identity id")
        _validate_identifier(self.provider_id, "identity provider id")
        _validate_text(self.display_name, "identity display name")
        _validate_timestamps(self)
        _validate_string_tuple(self.scopes, "scopes")
        if self.credential_ref is not None:
            _validate_identifier(self.credential_ref, "credential reference")


@dataclass(frozen=True, slots=True)
class ProviderConnection(JsonContract):
    connection_id: str
    provider_id: str
    display_name: str
    created_at: datetime
    updated_at: datetime
    identity_id: str | None = None
    account_hint: str | None = None
    scopes: tuple[str, ...] = ()
    credential_ref: str | None = None
    expires_at: datetime | None = None
    last_checked_at: datetime | None = None
    automatic_allowed: bool = True

    def __post_init__(self) -> None:
        _validate_identifier(self.connection_id, "connection id")
        _validate_identifier(self.provider_id, "provider id")
        _validate_text(self.display_name, "connection display name")
        if self.identity_id is not None:
            _validate_identifier(self.identity_id, "identity id")
        if self.credential_ref is not None:
            _validate_identifier(self.credential_ref, "credential reference")
        _validate_string_tuple(self.scopes, "scopes")
        _validate_timestamps(self)


def _validate_timestamps(contract: ProviderIdentity | ProviderConnection) -> None:
    for field_name in ("created_at", "updated_at", "expires_at", "last_checked_at"):
        _validate_optional_datetime(getattr(contract, field_name), field_name)


def _validate_string_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise TypeError(f"{field_name} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ProviderRuntimeState(JsonContract):
    provider_id: str
    installed: bool = False
    configured: bool = False
    authenticated: bool = False
    reachable: bool = False
    operational: bool = False
    automatic_allowed: bool = True
    checking: bool = False
    checked_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.provider_id, "provider id")
        _validate_optional_datetime(self.checked_at, "checked_at")


def derive_display_status(
    state: ProviderRuntimeState,
    *,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> DisplayStatus:
    """Derive a UI status from independent runtime dimensions without I/O."""

    _validate_optional_datetime(expires_at, "expires_at")
    _validate_optional_datetime(now, "now")
    reference_time = now or datetime.now(timezone.utc)

    if not state.installed:
        return DisplayStatus.NOT_INSTALLED
    if not state.configured:
        return DisplayStatus.NOT_CONFIGURED
    if state.checking:
        return DisplayStatus.CHECKING
    if expires_at is not None and expires_at <= reference_time:
        return DisplayStatus.EXPIRED
    if not state.authenticated:
        return DisplayStatus.DISCONNECTED
    if state.operational:
        return DisplayStatus.OPERATIONAL
    if state.last_error_code:
        return DisplayStatus.ERROR
    if state.reachable:
        return DisplayStatus.CONNECTED
    return DisplayStatus.DEGRADED
