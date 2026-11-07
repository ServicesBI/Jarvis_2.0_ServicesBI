"""Contratos HTTP para configuração dos executores locais."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/executor", tags=["executors"])


@router.get("/mode")
async def get_executor_mode(request: Request) -> dict[str, object]:
    executor_manager = request.app.state.executor_manager
    return {
        "mode": executor_manager.get_mode(),
        "validModes": list(executor_manager.valid_modes),
    }


@router.post("/mode")
async def set_executor_mode(request: Request) -> JSONResponse:
    executor_manager = request.app.state.executor_manager
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None

    requested_mode = payload.get("mode") if isinstance(payload, dict) else None
    try:
        mode = executor_manager.set_mode(requested_mode)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "Modo inválido",
                "validModes": list(executor_manager.valid_modes),
            },
        )
    return JSONResponse(content={"ok": True, "mode": mode})


def _provider_status(state, profiles: list[dict[str, object]]) -> str:
    if state.status != "online":
        return state.status
    if not any(item["available"] and item["enabled"] for item in profiles):
        return "profile_unavailable"
    return "online"


@router.get("/profiles")
async def get_executor_profiles(request: Request) -> dict[str, object]:
    manager = request.app.state.executor_manager
    availability = request.app.state.provider_availability
    await availability.refresh()
    catalog = manager.model_registry.catalog()
    providers = []
    for provider in ("codex", "claude"):
        profiles = [catalog[provider][name] for name in ("max", "pro", "fast")]
        state = availability.get_state(provider)
        provider_status = _provider_status(state, profiles)
        if provider_status != "online":
            profiles = [
                {**profile, "status": provider_status, "reason": state.reason}
                for profile in profiles
            ]
        providers.append(
            {
                "provider": provider,
                "active_profile": manager.get_profile(provider),
                "status": provider_status,
                "availability": state.eligible,
                "reason": state.reason,
                "profiles": profiles,
            }
        )
    return {"providers": providers}


@router.post("/profiles")
async def set_executor_profile(request: Request) -> JSONResponse:
    manager = request.app.state.executor_manager
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None
    provider = payload.get("provider") if isinstance(payload, dict) else None
    profile = payload.get("profile") if isinstance(payload, dict) else None
    try:
        active_profile = manager.set_profile(str(provider or ""), profile)
    except ValueError as error:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(error)})
    except Exception as error:
        reason = getattr(error, "reason", "profile_unavailable")
        return JSONResponse(status_code=409, content={"ok": False, "error": reason})
    return JSONResponse(
        content={"ok": True, "provider": provider, "active_profile": active_profile}
    )
