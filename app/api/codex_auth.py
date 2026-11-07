"""Endpoints internos para conexão oficial do Codex CLI."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import LOCAL_ORIGINS
from app.executors.codex_auth import (
    CodexAuthCommandError,
    CodexAuthTimeoutError,
    CodexAuthUnsupportedError,
    CodexNotInstalledError,
)


router = APIRouter(prefix="/api/integrations/codex", tags=["codex-auth"])
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
    if isinstance(error, CodexNotInstalledError):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "status": "not_installed", "error": "Codex CLI não encontrado"},
        )
    if isinstance(error, CodexAuthTimeoutError):
        return JSONResponse(
            status_code=504,
            content={"ok": False, "status": "timeout", "error": "Tempo limite do fluxo Codex excedido"},
        )
    if isinstance(error, CodexAuthUnsupportedError):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "status": "unsupported",
                "error": "Autenticação controlada pelo ambiente não permite esta operação",
            },
        )
    return JSONResponse(
        status_code=502,
        content={"ok": False, "status": "error", "error": "Falha no comando oficial do Codex"},
    )


async def _refresh_provider_snapshot(request: Request) -> None:
    await request.app.state.provider_availability.refresh_provider("codex")


@router.get("/status")
async def codex_connection_status(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    return await request.app.state.codex_auth_service.status()


@router.post("/connect")
async def connect_codex(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    try:
        response = await request.app.state.codex_auth_service.connect()
        await _refresh_provider_snapshot(request)
        return response
    except (CodexNotInstalledError, CodexAuthTimeoutError, CodexAuthUnsupportedError, CodexAuthCommandError) as error:
        return _auth_error(error)


@router.post("/disconnect")
async def disconnect_codex(request: Request):
    if not _local_request_allowed(request):
        return _forbidden()
    try:
        response = await request.app.state.codex_auth_service.disconnect()
        await _refresh_provider_snapshot(request)
        return response
    except (CodexNotInstalledError, CodexAuthTimeoutError, CodexAuthUnsupportedError, CodexAuthCommandError) as error:
        return _auth_error(error)
