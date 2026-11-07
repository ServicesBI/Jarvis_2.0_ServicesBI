"""Endpoints locais para autenticação oficial do Claude Code CLI."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import LOCAL_ORIGINS
from app.executors.claude_auth import (
    ClaudeAuthCommandError,
    ClaudeAuthTimeoutError,
    ClaudeNotInstalledError,
)


router = APIRouter(prefix="/api/integrations/claude", tags=["claude-auth"])
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "testclient"}


def _local_request_allowed(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    origin = request.headers.get("origin")
    return client_host in _LOCAL_CLIENTS and (not origin or origin in LOCAL_ORIGINS)


def _forbidden() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"ok": False, "error": "Local request required"},
    )


def _auth_error(error: Exception) -> JSONResponse:
    if isinstance(error, ClaudeNotInstalledError):
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "status": "not_installed",
                "error": "Claude Code CLI não encontrado",
            },
        )
    if isinstance(error, ClaudeAuthTimeoutError):
        return JSONResponse(
            status_code=504,
            content={
                "ok": False,
                "status": "timeout",
                "error": "Tempo limite do fluxo Claude excedido",
            },
        )
    return JSONResponse(
        status_code=502,
        content={
            "ok": False,
            "status": "error",
            "error": "Falha no comando oficial do Claude Code",
        },
    )


async def _refresh_provider_availability(request: Request) -> None:
    await request.app.state.provider_availability.refresh_provider("claude")


@router.get("/status")
async def claude_connection_status(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    return await request.app.state.claude_auth_service.status()


@router.post("/connect")
async def connect_claude(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    try:
        response = await request.app.state.claude_auth_service.connect()
        await _refresh_provider_availability(request)
        return response
    except (
        ClaudeNotInstalledError,
        ClaudeAuthTimeoutError,
        ClaudeAuthCommandError,
    ) as error:
        return _auth_error(error)


@router.post("/disconnect")
async def disconnect_claude(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    try:
        response = await request.app.state.claude_auth_service.disconnect()
        await _refresh_provider_availability(request)
        return response
    except (
        ClaudeNotInstalledError,
        ClaudeAuthTimeoutError,
        ClaudeAuthCommandError,
    ) as error:
        return _auth_error(error)
