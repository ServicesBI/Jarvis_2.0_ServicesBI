"""Endpoint de saúde da aplicação FastAPI."""

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    """Informa o estado real da fundação FastAPI no PASSO 0A."""

    openai_ready = bool(request.app.state.openai_gateway.configured)
    availability = request.app.state.provider_availability
    return {
        "status": "ok",
        "components": {
            "server": {"status": "ok"},
            "openai": {
                "status": "ok" if openai_ready else "error",
                "error": None if openai_ready else "OPENAI_API_KEY is not configured",
            },
            "claude": availability.get_state("claude").health_payload(),
            "chrome": {
                "status": "not_checked",
                "required": False,
            },
            "pools": {
                "opus": 0,
                "sonnet": 0,
                "haiku": 0,
                "spawnErrors": 0,
            },
        },
        "capabilities": {
            "voice_realtime": openai_ready,
            "voice_stt": openai_ready,
            "voice_tts": openai_ready,
            "task_execution": True,
            "task_lifecycle": True,
            "pdf_generation": False,
            "screen_analysis": openai_ready,
            "excel_live": True,
            "meta_ads": False,
        },
    }
