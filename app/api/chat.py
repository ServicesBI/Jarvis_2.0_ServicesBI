"""Camada HTTP e de streaming do chat do JARVIS."""

from dataclasses import replace

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.actions.models import ActionRequest
from app.chat.action_dispatcher import ExcelContentDraft, FileOpenIntent, WordContentDraft
from app.chat.models import ChatRequest


router = APIRouter(prefix="/api", tags=["chat"])

STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Transfer-Encoding": "chunked",
}


async def _stream_task_result(request: Request, task: dict[str, object]):
    task_id = str(task["task_id"])
    yield f"[info] Tarefa registrada: {task_id} (queued)\n"
    finished = await request.app.state.task_manager.wait(task_id, timeout=35.0)
    if finished["status"] == "completed":
        result = finished.get("result") or {}
        artifacts = result.get("artifacts") or []
        first_artifact = artifacts[0] if artifacts else {}
        path = first_artifact.get("path") or result.get("path")
        yield f"[system] Tarefa {task_id} concluida com efeito real.\n"
        summary = result.get("summary")
        if isinstance(summary, str) and summary.strip():
            yield f"[system] {summary.strip()}\n"
        if path:
            yield f"[file] {path} | {path}\n"
    else:
        error = finished.get("error") or "falha sem detalhe"
        yield f"[error] Tarefa {task_id} {finished['status']}: {error}\n"


def _action_response(request: Request, action_request: ActionRequest) -> StreamingResponse:
    task = request.app.state.action_engine.submit(action_request)
    return StreamingResponse(
        _stream_task_result(request, task),
        status_code=200,
        media_type="text/plain",
        headers=STREAM_HEADERS,
    )


def _file_open_response(request: Request, intent: FileOpenIntent) -> StreamingResponse:
    async def stream_file_open():
        try:
            resolve_task = request.app.state.action_engine.submit(
                ActionRequest(
                    action="file.resolve",
                    arguments={"name": intent.name},
                    source="chat",
                )
            )
            resolved = await request.app.state.task_manager.wait(
                str(resolve_task["task_id"]), timeout=35.0
            )
        except Exception:
            yield "[error] Falha tecnica ao resolver o arquivo.\n"
            return

        if resolved.get("status") != "completed":
            yield "[error] Falha tecnica ao resolver o arquivo.\n"
            return

        result = resolved.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        status = data.get("status") if isinstance(data, dict) else None
        if status == "not_found":
            yield (
                f'[system] Nao encontrei "{intent.name}" em '
                "Documents and Projects.\n"
            )
            return
        if status == "ambiguous":
            candidates = data.get("candidates")
            if not isinstance(candidates, list) or not all(
                isinstance(candidate, str) for candidate in candidates
            ):
                yield "[error] Falha tecnica ao resolver o arquivo.\n"
                return
            yield "[system] Encontrei mais de um arquivo com esse nome:\n"
            for candidate in candidates:
                yield f"- {candidate}\n"
            yield "Informe qual deles voce quer abrir.\n"
            return
        if status != "found":
            yield "[error] Falha tecnica ao resolver o arquivo.\n"
            return

        path = data.get("path")
        if not isinstance(path, str) or not path:
            yield "[error] Falha tecnica ao resolver o arquivo.\n"
            return

        try:
            open_task = request.app.state.action_engine.submit(
                ActionRequest(
                    action="file.open",
                    arguments={"path": path},
                    source="chat",
                )
            )
            opened = await request.app.state.task_manager.wait(
                str(open_task["task_id"]), timeout=35.0
            )
        except Exception:
            yield "[error] Encontrei o arquivo, mas nao consegui abri-lo.\n"
            return

        if opened.get("status") != "completed":
            yield "[error] Encontrei o arquivo, mas nao consegui abri-lo.\n"
            return

        open_result = opened.get("result")
        open_data = open_result.get("data") if isinstance(open_result, dict) else None
        if not isinstance(open_data, dict):
            yield "[error] Encontrei o arquivo, mas nao consegui abri-lo.\n"
            return
        filename = open_data.get("file")
        application = open_data.get("application")
        if not isinstance(filename, str) or not isinstance(application, str):
            yield "[error] Encontrei o arquivo, mas nao consegui abri-lo.\n"
            return
        application_label = {
            "excel": "Excel",
            "word": "Word",
            "powerbi": "Power BI",
        }.get(application, application)
        yield f"[system] Abri {filename} no {application_label}.\n"

    return StreamingResponse(
        stream_file_open(),
        status_code=200,
        media_type="text/plain",
        headers=STREAM_HEADERS,
    )


def _elaborated_action_response(
    request: Request,
    chat_request: ChatRequest,
    draft: WordContentDraft,
) -> StreamingResponse:
    async def stream_elaboration():
        elaboration_request = replace(
            chat_request,
            message=draft.elaboration_prompt,
        )
        chunks = [
            chunk
            async for chunk in request.app.state.chat_service.stream(
                elaboration_request,
                request.is_disconnected,
            )
        ]
        content = "".join(chunks).strip()
        if not content:
            yield "[error] O provider não retornou conteúdo para o documento Word.\n"
            return
        if content.startswith("[error]"):
            yield content if content.endswith("\n") else content + "\n"
            return
        try:
            task = request.app.state.action_engine.submit(
                draft.to_action_request(content)
            )
        except Exception as error:
            yield f"[error] Falha ao registrar a action Word: {error}\n"
            return
        async for chunk in _stream_task_result(request, task):
            yield chunk

    return StreamingResponse(
        stream_elaboration(),
        status_code=200,
        media_type="text/plain",
        headers=STREAM_HEADERS,
    )


def _elaborated_excel_response(
    request: Request,
    chat_request: ChatRequest,
    draft: ExcelContentDraft,
) -> StreamingResponse:
    async def stream_elaboration():
        elaboration_request = replace(
            chat_request,
            message=draft.elaboration_prompt,
        )
        chunks = [
            chunk
            async for chunk in request.app.state.chat_service.stream(
                elaboration_request,
                request.is_disconnected,
            )
        ]
        content = "".join(chunks).strip()
        if not content:
            yield "[error] O provider nao retornou estrutura para a planilha Excel.\n"
            return
        if content.startswith("[error]"):
            yield content if content.endswith("\n") else content + "\n"
            return
        try:
            action_request = draft.to_action_request(content)
        except (ValidationError, ValueError):
            yield "[error] Estrutura Excel invalida retornada pelo provider.\n"
            return
        try:
            task = request.app.state.action_engine.submit(action_request)
        except Exception as error:
            yield f"[error] Falha ao registrar a action Excel: {error}\n"
            return
        async for chunk in _stream_task_result(request, task):
            yield chunk

    return StreamingResponse(
        stream_elaboration(),
        status_code=200,
        media_type="text/plain",
        headers=STREAM_HEADERS,
    )


def _chat_request_from_payload(payload: object) -> ChatRequest | None:
    if not isinstance(payload, dict):
        return None

    message = payload.get("message")
    if not isinstance(message, str) or not message:
        return None

    attachment_id = payload.get("attachmentId")
    language = payload.get("language", "BR")
    return ChatRequest(
        message=message,
        attachment_id=attachment_id if isinstance(attachment_id, str) else None,
        from_voice=payload.get("fromVoice") is True,
        language=language if isinstance(language, str) and language else "BR",
        conclave_enabled=payload.get("conclaveEnabled", True) is not False,
    )


@router.post("/chat")
async def chat(request: Request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None

    chat_request = _chat_request_from_payload(payload)
    if chat_request is None:
        return JSONResponse(status_code=400, content={"error": "Message required"})

    action_dispatcher = request.app.state.action_dispatcher
    resolution = action_dispatcher.resolve(chat_request.message)
    if isinstance(resolution, ActionRequest):
        return _action_response(request, resolution)
    if isinstance(resolution, WordContentDraft):
        return _elaborated_action_response(request, chat_request, resolution)
    if isinstance(resolution, ExcelContentDraft):
        return _elaborated_excel_response(request, chat_request, resolution)
    if isinstance(resolution, FileOpenIntent):
        return _file_open_response(request, resolution)

    chat_service = request.app.state.chat_service
    return StreamingResponse(
        chat_service.stream(chat_request, request.is_disconnected),
        status_code=200,
        media_type="text/plain",
        headers=STREAM_HEADERS,
    )
