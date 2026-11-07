"""Rotas HTTP de diagnóstico do Jarvis."""

import asyncio

from fastapi import APIRouter, Request

from app.core import diagnostics


router = APIRouter(prefix="/api", tags=["diagnostics"])


@router.get("/stats")
async def stats() -> dict[str, object]:
    """Retorna as métricas da sessão atual do backend FastAPI."""

    return diagnostics.get_session_stats()


@router.get("/system-stats")
async def system_stats() -> dict[str, object]:
    """Coleta métricas locais sem tornar dependências opcionais obrigatórias."""

    return await asyncio.to_thread(diagnostics.collect_system_stats)


@router.get("/providers/health")
async def providers_health(request: Request) -> dict[str, object]:
    """Projeta a disponibilidade autoritativa sem executar chat ou modelo."""

    availability = request.app.state.provider_availability
    manager = request.app.state.executor_manager
    await availability.refresh()
    return {
        **diagnostics.get_local_service_health(),
        "claude": availability.get_state("claude").health_payload(),
        "codex": availability.get_state("codex").health_payload(),
        "executor": {
            "mode": manager.get_mode(),
            "validModes": list(manager.valid_modes),
            "fallbackEnabled": manager.get_mode() == "auto",
        },
    }
