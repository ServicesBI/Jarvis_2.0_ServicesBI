"""Contratos auxiliares ativos usados pelo cockpit do Jarvis."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import LOCAL_ORIGINS, PROJECT_ROOT, get_setting


router = APIRouter(prefix="/api", tags=["compatibility"])
OPENAI_BALANCE_BRIDGE_ORIGIN = "chrome-extension://aacaopfflcfcocgpnklfggpmkjacbilc"


class OpenAIBalanceIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    balance_usd: float = Field(strict=True, ge=0, le=1_000_000)
    currency: Literal["USD"]
    observed_at: datetime
    source: Literal["openai_platform_home"]


class OpenAIBalanceHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["content_script_loaded", "credit_balance_found", "ingest_sent", "ingest_accepted", "ingest_rejected"]
    page_url: Literal["https://platform.openai.com/home"]


def _local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    origin = request.headers.get("origin")
    local_host = host in {"127.0.0.1", "::1", "localhost", "testclient"}
    return local_host and (not origin or origin.rstrip("/") in LOCAL_ORIGINS)


@router.get("/connections/providers")
async def connection_providers() -> dict[str, object]:
    return {"providers": [], "categories": [], "checkedAt": datetime.now(timezone.utc).isoformat()}


@router.get("/weather")
async def weather(city: str = "Brasilia") -> JSONResponse:
    place = city.strip() or "Brasilia"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(
                f"https://wttr.in/{place}", params={"format": "j1"}, headers={"User-Agent": "curl/7.0"}
            )
            response.raise_for_status()
            data = response.json()
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        name = area.get("areaName", [{"value": place}])[0].get("value", place)
        description = current.get("weatherDesc", [{"value": ""}])[0].get("value", "")
        return JSONResponse({
            "city": name,
            "temp": current.get("temp_C"),
            "feelsLike": current.get("FeelsLikeC"),
            "humidity": current.get("humidity"),
            "description": description,
            "summary": f"{name}: {current.get('temp_C', '--')}°C, {description}",
        })
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return JSONResponse({"error": "Weather service unavailable"}, status_code=502)


@router.post("/config")
async def save_config(request: Request) -> JSONResponse:
    if not _local_request(request):
        return JSONResponse({"error": "Local request required"}, status_code=403)
    payload = await request.json()
    if payload.get("key") != "OPENAI_API_KEY":
        return JSONResponse({"error": "Only OPENAI_API_KEY can be configured"}, status_code=400)
    value = str(payload.get("value", "")).replace("\r", "").replace("\n", "")
    env_path = PROJECT_ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        updated: list[str] = []
        replaced = False
        for line in lines:
            if line.lstrip().startswith("OPENAI_API_KEY="):
                updated.append(f"OPENAI_API_KEY={value}")
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(f"OPENAI_API_KEY={value}")
        env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    except OSError:
        return JSONResponse({"error": "Configuration could not be saved"}, status_code=500)
    return JSONResponse({"ok": True})


@router.get("/openai-balance")
@router.get("/agenda/balance")
async def openai_balance(request: Request) -> JSONResponse:
    state = await request.app.state.openai_costs_ledger_service.current()
    return JSONResponse(state, headers={"Cache-Control": "no-store"})


@router.post("/openai-balance/ingest", status_code=202)
async def ingest_openai_balance(payload: OpenAIBalanceIngest, request: Request) -> JSONResponse:
    origin = request.headers.get("origin")
    if origin != OPENAI_BALANCE_BRIDGE_ORIGIN:
        return JSONResponse({"accepted": False, "code": "BRIDGE_ORIGIN_REJECTED"}, status_code=403)
    state = await request.app.state.openai_balance_service.ingest(
        payload.balance_usd, observed_at=payload.observed_at.isoformat(),
        extension_id=origin.removeprefix("chrome-extension://"),
    )
    return JSONResponse({"accepted": True, "updated_at": state["updated_at"]}, status_code=202)


@router.post("/openai-balance/heartbeat", status_code=202)
async def openai_balance_heartbeat(payload: OpenAIBalanceHeartbeat, request: Request) -> JSONResponse:
    origin = request.headers.get("origin")
    if origin != OPENAI_BALANCE_BRIDGE_ORIGIN:
        return JSONResponse({"accepted": False, "code": "BRIDGE_ORIGIN_REJECTED"}, status_code=403)
    observed_at = datetime.now(timezone.utc).isoformat()
    await request.app.state.openai_balance_service.heartbeat(
        extension_id=origin.removeprefix("chrome-extension://"), stage=payload.stage, observed_at=observed_at
    )
    return JSONResponse({"accepted": True, "stage": payload.stage}, status_code=202)


@router.get("/openai-balance/bridge-status")
async def openai_balance_bridge_status(request: Request) -> JSONResponse:
    return JSONResponse(request.app.state.openai_balance_service.bridge_status(), headers={"Cache-Control": "no-store"})


@router.post("/health/preflight")
async def preflight(request: Request) -> dict[str, object]:
    configured = bool(get_setting("OPENAI_API_KEY"))
    results = {
        "openai_api": {"ok": configured, "detail": "configured" if configured else "OPENAI_API_KEY missing"},
        "openai_realtime": {"ok": configured, "detail": "route available; no paid probe executed"},
        "openai_tts": {"ok": configured, "detail": "route available; no paid probe executed"},
        "claude_cli": {"ok": False, "detail": "not probed by FastAPI preflight"},
        "claude_execute": {"ok": False, "detail": "not probed by FastAPI preflight"},
    }
    ready = configured
    return {"status": "ready" if ready else "issues_found", "results": results, "message": "Configuration-only preflight completed"}


@router.post("/health/autofix")
async def autofix() -> PlainTextResponse:
    return PlainTextResponse(
        "Autofix indisponivel no backend FastAPI; nenhuma alteracao foi executada.\n[autofix-done]",
        status_code=503,
    )


@router.post("/pet/mic-state")
async def pet_mic_state(request: Request) -> dict[str, bool]:
    payload = await request.json()
    active = bool(payload.get("active", payload.get("listening", False)))
    await request.app.state.notification_broker.publish({"type": "pet-mic", "active": active})
    return {"ok": True, "active": active}


@router.post("/pet/launch")
async def pet_launch(request: Request) -> JSONResponse:
    process = request.app.state.pet_process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 5)
        except subprocess.TimeoutExpired:
            return JSONResponse({"ok": False, "error": "Desktop Pet did not close gracefully"}, status_code=503)
        request.app.state.pet_process = None
        return JSONResponse({"ok": True, "action": "closed", "message": "Desktop Pet fechado."})
    candidates = [
        PROJECT_ROOT / "pet" / "node_modules" / "electron" / "dist" / "electron.exe",
        PROJECT_ROOT / "pet" / "node_modules" / ".bin" / "electron.cmd",
    ]
    executable = next((item for item in candidates if item.exists()), None)
    if executable is None:
        return JSONResponse({"ok": False, "error": "Desktop Pet unavailable"}, status_code=503)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        request.app.state.pet_process = subprocess.Popen(
            [str(executable), str(PROJECT_ROOT / "pet")],
            cwd=PROJECT_ROOT / "pet",
            creationflags=flags,
        )
    except OSError:
        return JSONResponse({"ok": False, "error": "Desktop Pet could not be started"}, status_code=500)
    return JSONResponse({"ok": True, "action": "opened", "message": "Desktop Pet aberto."})
