"""Contratos de voz, Realtime, traducao, TTS, STT, visao e cowork."""

from __future__ import annotations

import re
import os
import shutil
import subprocess
import webbrowser
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.actions.models import ActionRequest
from app.core.config import PROJECT_ROOT, get_setting
from app.core.openai_gateway import OpenAIGateway, UpstreamError


router = APIRouter(prefix="/api", tags=["voice"])

VALID_VOICES = {"alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}
REALTIME_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"}
REALTIME_LANGUAGES = {"BR", "ES", "EN"}
HALLUCINATIONS = (
    re.compile(r"^\.+$"),
    re.compile(r"^(bye|goodbye|thank you for watching|tchau|adeus|silence|music|okay|ok)\.?$", re.I),
    re.compile(r"^[\[(].*[\])]$"),
)
SCREEN_PATTERN = re.compile(r"\b(tela|screen|monitor|screenshot|captura)\b", re.I)
SHEET_PATTERN = re.compile(r"\b(excel|planilha|spreadsheet|xlsx)\b", re.I)

INSTRUCTIONS = {
    "BR": "Voce e JARVIS, assistente pessoal do usuario. Fale apenas em Portugues Brasileiro, de forma direta. Para pedidos de acao, chame execute_task com o pedido integral.",
    "ES": "Eres JARVIS, asistente personal del usuario. Habla solo en Espanol y llama execute_task para solicitudes de accion.",
    "EN": "You are JARVIS, the user's personal assistant. Speak only English and call execute_task for action requests.",
}


def _gateway(request: Request) -> OpenAIGateway:
    return request.app.state.openai_gateway


def _multipart_file(content_type: str, body: bytes, field: str) -> tuple[str, str, bytes] | None:
    if "multipart/form-data" not in content_type.lower():
        return None
    envelope = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + body
    )
    message = BytesParser(policy=policy.default).parsebytes(envelope)
    if not message.is_multipart():
        return None
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") == field:
            filename = part.get_filename() or f"{field}.bin"
            mime = part.get_content_type() or "application/octet-stream"
            return filename, mime, part.get_payload(decode=True) or b""
    return None


def _is_hallucination(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 4 or (" " not in cleaned and len(cleaned) < 8):
        return True
    if any(pattern.match(cleaned) for pattern in HALLUCINATIONS):
        return True
    words = cleaned.lower().split()
    return len(words) >= 3 and len(set(words)) <= len(words) * 0.3


@router.post("/realtime/session")
async def realtime_session(request: Request) -> JSONResponse:
    payload = await request.json()
    language = str(payload.get("language", "BR")).upper()
    voice = str(payload.get("voice", "ash")).strip().lower()
    if language not in REALTIME_LANGUAGES:
        return JSONResponse(
            {"code": "INVALID_REALTIME_LANGUAGE", "error": "Unsupported realtime language"},
            status_code=400,
        )
    if voice not in REALTIME_VOICES:
        return JSONResponse(
            {"code": "INVALID_REALTIME_VOICE", "error": "Unsupported realtime voice"},
            status_code=400,
        )
    gateway = _gateway(request)
    if not gateway.configured:
        return JSONResponse(
            {"code": "OPENAI_KEY_MISSING", "error": "OpenAI API key not configured"},
            status_code=503,
        )
    model = get_setting("OPENAI_REALTIME_MODEL") or "gpt-realtime-2.1"
    try:
        result = await gateway.create_realtime_session(
            language=language,
            voice=voice,
            model=model,
            instructions=INSTRUCTIONS.get(language, INSTRUCTIONS["BR"]),
        )
    except UpstreamError as exc:
        if exc.status_code == 502:
            return JSONResponse(
                {"code": "REALTIME_UPSTREAM_ERROR", "error": "Realtime service unavailable"},
                status_code=502,
            )
        return JSONResponse(
            {"code": "REALTIME_SESSION_REFUSED", "error": exc.message},
            status_code=exc.status_code,
        )
    return JSONResponse(
        {"value": result.get("value"), "expires_at": result.get("expires_at"), "model": model}
    )


@router.post("/stt")
async def stt(request: Request) -> JSONResponse:
    gateway = _gateway(request)
    if not gateway.configured:
        return JSONResponse({"error": "OpenAI API key not configured"}, status_code=500)
    parsed = _multipart_file(request.headers.get("content-type", ""), await request.body(), "audio")
    if parsed is None:
        return JSONResponse({"error": "No audio file"}, status_code=400)
    filename, mime, audio = parsed
    if len(audio) < 2000:
        return JSONResponse({"text": "", "filtered": True, "reason": "Audio too short"})
    try:
        text = await gateway.transcribe(audio, filename=filename, content_type=mime, language="en")
        if _is_hallucination(text):
            text = await gateway.transcribe(audio, filename=filename, content_type=mime, language="pt")
    except UpstreamError as exc:
        return JSONResponse({"error": exc.message}, status_code=500)
    if _is_hallucination(text):
        return JSONResponse(
            {"text": "", "filtered": True, "reason": "Could not understand. Try speaking closer to the mic."}
        )
    return JSONResponse({"text": text})


@router.post("/tts")
async def tts(request: Request) -> Response:
    gateway = _gateway(request)
    if not gateway.configured:
        return JSONResponse({"error": "OpenAI API key not configured"}, status_code=500)
    payload = await request.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "Text required"}, status_code=400)
    language = str(payload.get("language", "BR")).upper()
    requested = str(payload.get("voice", ""))
    voice = requested if requested in VALID_VOICES else ("nova" if language == "BR" else "onyx")
    try:
        audio = await gateway.synthesize(text=text, voice=voice)
    except UpstreamError as exc:
        return JSONResponse({"error": exc.message}, status_code=500)
    return Response(audio, media_type="audio/mpeg")


@router.post("/translate")
async def translate(request: Request) -> dict[str, str]:
    payload = await request.json()
    text = str(payload.get("text", ""))
    if not text:
        return {"translated": text}
    target = str(payload.get("targetLang", "EN")).upper()
    language_name = {"BR": "Brazilian Portuguese", "ES": "Spanish", "EN": "English"}.get(target, "English")
    gateway = _gateway(request)
    if not gateway.configured:
        return {"translated": text}
    try:
        translated = await gateway.complete(
            messages=[
                {"role": "system", "content": f"Translate to {language_name}. Return only the translation."},
                {"role": "user", "content": text},
            ],
            max_tokens=500,
        )
        return {"translated": translated or text}
    except UpstreamError:
        return {"translated": text}


def _fast_command(message: str, language: str) -> dict[str, Any] | None:
    text = re.sub(r"^jarvis[,.]?\s*", "", message.lower().strip())
    if re.match(r"^(bom dia|boa tarde|boa noite|ola|olá|oi|hello|hey)\b", text):
        now = datetime.now()
        greeting = "Bom dia" if now.hour < 12 else ("Boa tarde" if now.hour < 18 else "Boa noite")
        summary = f"{greeting}, senhor. São {now:%H:%M}. O que posso fazer pelo senhor?" if language == "BR" else f"At your service. It is {now:%H:%M}."
        return {"summary": summary, "output": "[system] Saudação"}
    if re.search(r"\b(est[aá] a[ií]|est[aá] online|est[aá] funcionando|me escuta|me ouve|online and ready)\b", text):
        return {"summary": "Sim, senhor. Estou online." if language == "BR" else "Yes, sir. Online and ready.", "output": "[system] Status"}
    if re.search(r"\b(que horas|what time|hora atual|hora agora|data de hoje|what day)\b", text):
        now = datetime.now()
        return {"summary": f"São {now:%H:%M}, {now:%d/%m/%Y}." if language == "BR" else f"It is {now:%H:%M}, {now:%Y-%m-%d}.", "output": f"[system] {now:%H:%M - %d/%m/%Y}"}
    sites = {
        "youtube": "https://www.youtube.com",
        "spotify": "https://open.spotify.com",
        "instagram": "https://www.instagram.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "whatsapp": "https://web.whatsapp.com",
        "twitter": "https://x.com",
        "linkedin": "https://www.linkedin.com",
        "netflix": "https://www.netflix.com",
        "claude": "https://claude.ai",
        "chatgpt": "https://chat.openai.com",
        "notion": "https://www.notion.so",
        "figma": "https://www.figma.com",
        "canva": "https://www.canva.com",
        "trello": "https://trello.com",
        "vercel": "https://vercel.com",
        "supabase": "https://supabase.com",
        "twitch": "https://www.twitch.tv",
        "reddit": "https://www.reddit.com",
        "amazon": "https://www.amazon.com.br",
        "mercado livre": "https://www.mercadolivre.com.br",
    }
    for name, url in sites.items():
        if name in text and re.search(r"\b(abre|abra|abrir|open)\b", text):
            webbrowser.open(url)
            return {"summary": f"{name} aberto." if language == "BR" else f"{name} opened.", "output": f"[file] {url}"}
    spotify = re.search(r"(?:toca|toque|play|coloca|reproduz|ouvir|escutar)\s+(.+?)\s+(?:no|on)\s+spotify", text)
    if spotify:
        query = spotify.group(1).strip()
        url = f"https://open.spotify.com/search/{quote_plus(query)}"
        webbrowser.open(url)
        return {"summary": f'Buscando "{query}" no Spotify.', "output": f"[system] spotify: {query}", "_route": "media"}
    youtube = re.search(r"(?:toca|toque|play|coloca|reproduz|pesquise|pesquisa|busca)\s+(?:a\s+)?(?:m[uú]sica\s+|v[ií]deo\s+)?(.+?)(?:\s+(?:no|on)\s+youtube)?$", text)
    if youtube and re.search(r"\b(toca|toque|play|m[uú]sica|v[ií]deo|youtube)\b", text):
        query = youtube.group(1).strip()
        if len(query) >= 4:
            url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            webbrowser.open(url)
            return {"summary": f'Tocando "{query}" no YouTube.', "output": f"[system] youtube: {query}", "_route": "media"}
    maps = re.search(r"(?:como cheg[ao]|rota (?:para|pra|at[eé])|naveg[ae] (?:para|pra|at[eé])|directions? to|route to)\s+(.+)", text)
    if maps:
        destination = maps.group(1).strip()
        url = f"https://www.google.com/maps/search/{quote_plus(destination)}"
        webbrowser.open(url)
        return {"summary": "Abrindo mapa." if language == "BR" else "Opening map.", "output": f"[file] {url}"}
    search = re.search(r"(?:pesquise|pesquisa|buscar?|search(?: for)?)\s+(.+)", text)
    if search:
        url = f"https://www.google.com/search?q={quote_plus(search.group(1))}"
        webbrowser.open(url)
        return {"summary": "Pesquisando no Google." if language == "BR" else "Searching Google.", "output": f"[file] {url}"}
    timer = re.search(r"(?:timer|temporizador|alarme|alarm|cron[oô]metro)\s+(?:de|for|em)?\s*(\d+)\s*(min|minuto|minute|seg|segundo|second|hora|hour|h|m|s)", text)
    if timer:
        amount = int(timer.group(1))
        unit = timer.group(2).lower()
        seconds = amount * (3600 if unit in {"hora", "hour", "h"} else (60 if unit.startswith("min") or unit == "m" else 1))
        if 0 < seconds <= 86400:
            script = f"Start-Sleep -Seconds {seconds}; [System.Media.SystemSounds]::Exclamation.Play()"
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {"summary": f"Timer de {amount} {timer.group(2)} iniciado.", "output": f"[system] Timer {amount}{unit}"}
    volume = re.search(r"(?:volume|som)\s+(?:em|para|pra|to|at)?\s*(\d+)\s*%?", text)
    volume_action = None
    if re.search(r"\b(muta|mute|silenci[ao])\b", text):
        volume_action = "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"
    elif re.search(r"\b(aumenta|sobe|up)\b.*\b(volume|som)\b", text):
        volume_action = "1..5 | % { (New-Object -ComObject WScript.Shell).SendKeys([char]175) }"
    elif re.search(r"\b(diminui|abaixa|baixa|down)\b.*\b(volume|som)\b", text):
        volume_action = "1..5 | % { (New-Object -ComObject WScript.Shell).SendKeys([char]174) }"
    elif volume:
        level = min(max(int(volume.group(1)), 0), 100)
        presses = round(level / 2)
        volume_action = f"(New-Object -ComObject WScript.Shell).SendKeys([char]173); 1..{presses} | % {{ (New-Object -ComObject WScript.Shell).SendKeys([char]175) }}"
    if volume_action:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", volume_action],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {"summary": "Volume ajustado." if language == "BR" else "Volume adjusted.", "output": "[system] Volume ajustado"}
    if re.search(r"\b(deslig[ae]|shutdown|turn off)\s+(?:o\s+)?(?:pc|computador|computer|m[aá]quina)\b", text):
        return {"summary": "Desligamento do computador requer confirmação no executor.", "output": "[system] Shutdown solicitado"}
    if re.search(r"\b(reinici[ae]|restart|reboot)\s+(?:o\s+)?(?:pc|computador|computer|m[aá]quina)\b", text):
        return {"summary": "Reinicialização do computador requer confirmação no executor.", "output": "[system] Restart solicitado"}
    if re.search(r"\b(e|and|depois|then|tamb[eé]m|also)\b.*\b(cri[ae]|faz|make|create|edit|escrev|write|build|configur|preenche|digit|type)\b", text):
        return None
    programs = {
        "notepad": "notepad.exe", "bloco de notas": "notepad.exe",
        "calculadora": "calc.exe", "calculator": "calc.exe",
        "explorador": "explorer.exe", "explorer": "explorer.exe",
        "paint": "mspaint.exe", "powershell": "powershell.exe",
        "excel": "excel.exe", "word": "winword.exe", "powerpoint": "powerpnt.exe",
        "vscode": "code.cmd", "vs code": "code.cmd", "chrome": "chrome.exe",
        "edge": "msedge.exe", "firefox": "firefox.exe",
    }
    open_match = re.search(r"\b(?:abre|abra|abrir|open)\s+(?:o|a|meu|minha)?\s*(.+?)\s*$", text)
    if open_match:
        requested = open_match.group(1).strip()
        folder_match = re.match(r"(?:a\s+)?pasta\s+(.+)", requested)
        if folder_match:
            folder_name = folder_match.group(1).strip().strip("'\"")
            candidates = [
                Path.home() / folder_name,
                Path.home() / "Desktop" / folder_name,
                Path.home() / "Documents" / folder_name,
                Path.home() / "Downloads" / folder_name,
                PROJECT_ROOT / "Documents and Projects" / folder_name,
                Path(folder_name),
            ]
            folder = next((candidate.resolve() for candidate in candidates if candidate.is_dir()), None)
            if folder is not None:
                os.startfile(folder)
                return {"summary": f'Pasta "{folder_name}" aberta.', "output": f"[file] {folder}"}
        for name, command in programs.items():
            if re.fullmatch(re.escape(name) + r"(?:\s+pra mim|\s+por favor)?", requested):
                executable = shutil.which(command)
                if executable:
                    subprocess.Popen([executable], close_fds=True)
                    return {"summary": f"{name} aberto." if language == "BR" else f"{name} opened.", "output": f"[system] {name} iniciado"}
                return {"summary": f"{name} não está instalado." if language == "BR" else f"{name} is not installed.", "output": f"[error] {name} not installed"}
        url_match = re.fullmatch(r"(?:https?://)?([^\s]+\.[^\s]+)", requested)
        if url_match:
            url = requested if requested.startswith(("http://", "https://")) else f"https://{requested}"
            webbrowser.open(url)
            return {"summary": f"{url} aberto." if language == "BR" else f"{url} opened.", "output": f"[file] {url}"}
    return None


@router.post("/voice-command-router")
async def voice_command_router(request: Request) -> JSONResponse:
    payload = await request.json()
    message = str(payload.get("message", "")).strip()
    language = str(payload.get("language", "BR")).upper()
    if not message:
        return JSONResponse({"handled": False, "error": "Message required"}, status_code=400)
    if SCREEN_PATTERN.search(message) or SHEET_PATTERN.search(message):
        return JSONResponse({"handled": False, "reason": "chat_required"})
    resolution = request.app.state.action_dispatcher.resolve(message)
    if isinstance(resolution, ActionRequest):
        try:
            task = request.app.state.action_engine.submit(resolution)
        except (ValidationError, ValueError, PermissionError) as error:
            return JSONResponse(
                {
                    "handled": True,
                    "route": "action-error",
                    "action": resolution.action,
                    "summary": f"Não consegui iniciar a ação: {error}",
                    "output": f"[error] {error}",
                },
                status_code=400,
            )
        return JSONResponse(
            {
                "handled": True,
                "route": "action",
                "action": resolution.action,
                "task_id": task["task_id"],
                "status": task["status"],
                "summary": f"Tarefa {resolution.action} registrada.",
                "output": f"[info] Tarefa registrada: {task['task_id']} ({task['status']})",
            }
        )
    handler = getattr(request.app.state, "voice_command_handler", _fast_command)
    result = handler(message, language)
    if result:
        result = dict(result)
        route = result.pop("_route", "fast-path")
        return JSONResponse({"handled": True, "route": route, "output": "", **result})
    return JSONResponse({"handled": False, "reason": "no_fast_route"})


async def _vision(request: Request) -> JSONResponse:
    payload = await request.json()
    image = payload.get("image")
    if not image:
        return JSONResponse({"error": "Image required"}, status_code=400)
    gateway = _gateway(request)
    if not gateway.configured:
        return JSONResponse({"error": "OpenAI API key not configured"}, status_code=500)
    language = str(payload.get("language", "BR")).upper()
    message = str(payload.get("message", ""))
    question = message or ("Descreva o que esta nesta tela de forma util e direta." if language == "BR" else "Describe this screen usefully and directly.")
    try:
        answer = await gateway.complete(
            messages=[
                {"role": "system", "content": INSTRUCTIONS.get(language, INSTRUCTIONS["BR"])},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image, "detail": "auto"}},
                    {"type": "text", "text": question},
                ]},
            ]
        )
    except UpstreamError as exc:
        return JSONResponse({"error": exc.message}, status_code=500)
    return JSONResponse({"response": answer})


@router.post("/analyze-screen-fast")
async def analyze_screen_fast(request: Request) -> JSONResponse:
    return await _vision(request)


@router.post("/analyze-screen")
async def analyze_screen(request: Request) -> JSONResponse:
    return await _vision(request)


@router.post("/cowork/start")
async def cowork_start(request: Request) -> dict[str, object]:
    if request.app.state.cowork_active:
        return {"ok": True, "status": "already running"}
    request.app.state.cowork_active = True
    return {"ok": True, "status": "started"}


@router.post("/cowork/stop")
async def cowork_stop(request: Request) -> dict[str, object]:
    request.app.state.cowork_active = False
    return {"ok": True, "status": "stopped"}


@router.get("/cowork/status")
async def cowork_status(request: Request) -> dict[str, bool]:
    return {"active": bool(request.app.state.cowork_active)}
