"""Read-only HTTP projection of the central ProviderManager."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.executors.availability import ProviderAvailability
from app.providers.contracts import ProviderDomainError, ProviderErrorCode
from app.providers.manager import ProviderManager, ProviderSnapshot
from app.providers.models import Capability, ProviderCategory


router = APIRouter(prefix="/api/providers", tags=["providers"])


def _manager(request: Request) -> ProviderManager:
    return request.app.state.provider_manager


def _availability_display_status(state: ProviderAvailability) -> str:
    if not state.installed:
        return "not_installed"
    if not state.authenticated:
        return "disconnected"
    if state.operational:
        return "operational"
    return "degraded"


def _serialize_snapshot(
    snapshot: ProviderSnapshot,
    availability_state: ProviderAvailability | None = None,
) -> dict[str, Any]:
    definition = snapshot.definition
    state = snapshot.runtime_state
    operational_state = availability_state
    installed = operational_state.installed if operational_state else state.installed
    authenticated = (
        operational_state.authenticated if operational_state else state.authenticated
    )
    operational = (
        operational_state.operational if operational_state else state.operational
    )
    automatic_allowed = (
        operational_state.automatic_allowed
        if operational_state
        else state.automatic_allowed
    )
    reason = (
        operational_state.reason
        if operational_state
        else snapshot.display_status.value
    )
    return {
        "id": definition.id,
        "name": definition.name,
        "category": definition.category.value,
        "description": definition.description,
        "capabilities": [item.value for item in definition.capabilities],
        "auth_methods": [item.value for item in definition.auth_methods],
        "supports_multiple_accounts": definition.supports_multiple_accounts,
        "adapter_kind": definition.adapter_kind.value,
        "display_status": (
            _availability_display_status(operational_state)
            if operational_state
            else snapshot.display_status.value
        ),
        "runtime_state": {
            "installed": installed,
            "configured": state.configured,
            "authenticated": authenticated,
            "connected": authenticated,
            "reachable": state.reachable,
            "operational": operational,
            "automatic_allowed": automatic_allowed,
            "entitled": operational_state.entitled if operational_state else None,
            "eligible": operational_state.eligible if operational_state else False,
            "reason": reason,
            "checked_at": (
                state.checked_at.isoformat().replace("+00:00", "Z")
                if state.checked_at is not None
                else None
            ),
            "last_error_code": (
                (
                    None
                    if reason in {"operational", "status_connected", "configured"}
                    else reason
                )
                if operational_state
                else state.last_error_code
            ),
            "last_error_message": state.last_error_message,
        },
        "available_actions": [item.value for item in snapshot.available_actions],
        "automatic_allowed": automatic_allowed,
    }


def _serialize_provider(request: Request, snapshot: ProviderSnapshot) -> dict[str, Any]:
    try:
        availability_state = request.app.state.provider_availability.get_state(
            snapshot.definition.id
        )
    except ValueError:
        availability_state = None
    return _serialize_snapshot(snapshot, availability_state)


def _category(value: str | None) -> ProviderCategory | None:
    if value is None:
        return None
    try:
        return ProviderCategory(value.lower())
    except ValueError as error:
        raise HTTPException(400, "Invalid provider category.") from error


def _capability(value: str | None) -> Capability | None:
    if value is None:
        return None
    try:
        return Capability(value.lower())
    except ValueError as error:
        raise HTTPException(400, "Invalid provider capability.") from error


@router.get("")
async def list_providers(
    request: Request,
    category: str | None = Query(default=None),
    capability: str | None = Query(default=None),
) -> dict[str, Any]:
    manager = _manager(request)
    definitions = manager.list_definitions(
        category=_category(category),
        capability=_capability(capability),
    )
    providers = [
        _serialize_provider(request, manager.get_snapshot(definition.id))
        for definition in definitions
    ]
    return {"providers": providers, "count": len(providers)}


@router.get("/{provider_id}")
async def get_provider(provider_id: str, request: Request) -> dict[str, Any]:
    try:
        snapshot = _manager(request).get_snapshot(provider_id)
    except ProviderDomainError as error:
        if error.code is ProviderErrorCode.PROVIDER_NOT_FOUND:
            raise HTTPException(404, "Provider not found.") from error
        raise
    return _serialize_provider(request, snapshot)
