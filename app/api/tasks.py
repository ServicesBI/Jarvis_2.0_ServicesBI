"""API do lifecycle real de tarefas do Jarvis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.actions.models import ActionRequest
from app.tasks.manager import TaskTransitionError


router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
async def list_tasks(request: Request, limit: int = 100) -> dict[str, object]:
    manager = request.app.state.task_manager
    return {"tasks": manager.list(limit=limit)}


@router.get("/tasks/summary")
async def task_summary(request: Request) -> dict[str, object]:
    return request.app.state.task_manager.summary()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, object]:
    task = request.app.state.task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task nao encontrada.")
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict[str, object]:
    try:
        return await request.app.state.task_manager.cancel(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task nao encontrada.")
    except TaskTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/tasks", status_code=202)
async def create_task(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload invalido.")
    task_type = str(payload.get("type") or "")
    if task_type != "excel.create":
        raise HTTPException(status_code=400, detail="Tipo de task nao suportado.")
    excel_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    try:
        task = request.app.state.action_engine.submit(
            ActionRequest(
                action=task_type,
                arguments=excel_payload,
                source="api",
            )
        )
    except (ValidationError, ValueError, PermissionError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return task
