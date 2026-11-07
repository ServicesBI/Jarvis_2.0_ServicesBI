"""Task Manager persistente, com lifecycle e reconciliacao segura."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.registry import AgentRegistry
from app.db.models import TaskStatus
from app.db.repositories import TaskRepository


TaskOperation = Callable[[], Awaitable[dict[str, Any]]]
ACTIVE_STATUSES = {"pending", "running"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}
VALID_TRANSITIONS = {
    "pending": {"running", "cancelled", "failed"},
    "running": {"completed", "failed", "cancelled", "timeout"},
}


class TaskTransitionError(RuntimeError):
    """Indica uma tentativa invalida de alterar o lifecycle de uma task."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_PUBLIC_STATUS_TO_TASK_STATUS = {
    "pending": TaskStatus.PENDING,
    "running": TaskStatus.RUNNING,
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
    "cancelled": TaskStatus.CANCELLED,
}


def _public_status_to_repository(status: str) -> tuple[TaskStatus, str | None]:
    """Traduz o status público (que ainda inclui "timeout") para o par
    (TaskStatus, failure_code) do schema novo, que não tem "timeout"."""

    if status == "timeout":
        return TaskStatus.FAILED, "timeout"
    return _PUBLIC_STATUS_TO_TASK_STATUS[status], None


def _record_to_public(record: Any) -> dict[str, Any]:
    """Reconstrói o dict público (mesmo shape do modo arquivo) a partir de um
    TaskRecord — inclusive reconstruindo "timeout" quando failure_code indica
    isso, para manter o contrato público inalterado."""

    status = record.status.value if hasattr(record.status, "value") else str(record.status)
    if status == "failed" and record.failure_code == "timeout":
        status = "timeout"
    return {
        "task_id": record.id.hex,
        "type": record.type,
        "description": record.description,
        "executor": record.executor,
        "display_name": record.display_name,
        "agent_id": record.agent_id,
        "status": status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "result": record.result_json,
        "error": record.error_text,
    }


class TaskManager:
    """Registra, serializa, executa e cancela tarefas do Jarvis."""

    def __init__(
        self,
        state_path: Path | None = None,
        *,
        agent_registry: AgentRegistry | None = None,
        task_repository: TaskRepository | None = None,
    ) -> None:
        if (state_path is None) == (task_repository is None):
            raise ValueError(
                "TaskManager requer exatamente um de state_path ou "
                "task_repository, nunca os dois nem nenhum."
            )
        self.state_path = state_path
        self._task_repository = task_repository
        self._agent_registry = agent_registry
        self._lock = threading.RLock()
        self._desktop_lock = asyncio.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        if task_repository is None:
            self._load()
        # A construção apenas carrega o estado em memória. Reconciliação e
        # eventual persistência são lifecycle explícito (startup FastAPI).

    @property
    def agent_registry(self) -> AgentRegistry | None:
        return self._agent_registry

    def bind_agent_registry(self, agent_registry: AgentRegistry) -> None:
        if not isinstance(agent_registry, AgentRegistry):
            raise TypeError("agent_registry must be an AgentRegistry")
        if self._agent_registry is not None and self._agent_registry is not agent_registry:
            raise ValueError("TaskManager is already bound to another AgentRegistry")
        self._agent_registry = agent_registry

    @staticmethod
    def _interruption_error(existing: object, detail: str) -> str:
        current = str(existing or "").strip()
        return f"{current}; {detail}" if current else detail

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            items = payload.get("tasks", []) if isinstance(payload, dict) else []
        except (OSError, UnicodeError, json.JSONDecodeError):
            items = []

        for item in items:
            if not isinstance(item, dict) or not item.get("task_id"):
                continue
            task = dict(item)
            self._tasks[str(task["task_id"])] = task

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "tasks": list(self._tasks.values())}
        temp_path = self.state_path.with_name(
            f".{self.state_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(temp_path, self.state_path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def create(
        self,
        task_type: str,
        description: str,
        *,
        executor: str = "local",
        display_name: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        if agent_id is not None:
            if self._agent_registry is None:
                raise RuntimeError("TaskManager requires AgentRegistry for agent_id")
            self._agent_registry.get(agent_id)

        if self._task_repository is not None:
            record = self._task_repository.create(
                type=task_type,
                status=TaskStatus.PENDING,
                description=description,
                executor=executor,
                display_name=display_name,
                agent_id=agent_id,
            )
            return _record_to_public(record)

        task = {
            "task_id": uuid.uuid4().hex,
            "type": task_type,
            "description": description,
            "executor": executor,
            "display_name": display_name,
            "agent_id": agent_id,
            "status": "pending",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._tasks[task["task_id"]] = task
            self._persist()
        return dict(task)

    def transition(
        self,
        task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Executa a unica transicao de estado autorizada para uma task."""

        if self._task_repository is not None:
            with self._lock:
                uuid_id = uuid.UUID(task_id)
                record = self._task_repository.get(uuid_id)
                if record is None:
                    raise KeyError(task_id)
                current_public = _record_to_public(record)
                current = current_public["status"]
                if status not in VALID_TRANSITIONS.get(current, set()):
                    raise TaskTransitionError(
                        f"Task {task_id} nao pode transicionar de {current} para {status}."
                    )
                repo_status, failure_code = _public_status_to_repository(status)
                update_kwargs: dict[str, Any] = {}
                if status == "running":
                    update_kwargs["started_at"] = _utcnow()
                if status in TERMINAL_STATUSES:
                    update_kwargs["finished_at"] = _utcnow()
                    update_kwargs["result_json"] = result
                    update_kwargs["error_text"] = error
                if failure_code is not None:
                    update_kwargs["failure_code"] = failure_code
                updated = self._task_repository.update_status(
                    uuid_id, repo_status, **update_kwargs
                )
                return _record_to_public(updated)

        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            current = str(task.get("status"))
            if status not in VALID_TRANSITIONS.get(current, set()):
                raise TaskTransitionError(
                    f"Task {task_id} nao pode transicionar de {current} para {status}."
                )

            changes: dict[str, Any] = {"status": status}
            if status == "running":
                changes["started_at"] = _now()
            if status in TERMINAL_STATUSES:
                changes.update(finished_at=_now(), result=result, error=error)
            task.update(changes)
            self._persist()
            return dict(task)

    def submit(
        self,
        task_type: str,
        description: str,
        operation: TaskOperation,
        *,
        timeout: float = 60.0,
        desktop_exclusive: bool = True,
        executor: str = "local",
        display_name: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        task = self.create(
            task_type,
            description,
            executor=executor,
            display_name=display_name,
            agent_id=agent_id,
        )
        job = asyncio.create_task(
            self._execute(task["task_id"], operation, timeout, desktop_exclusive),
            name=f"jarvis-task-{task['task_id']}",
        )
        with self._lock:
            self._jobs[task["task_id"]] = job
        job.add_done_callback(
            lambda completed, task_id=task["task_id"]: self._discard_job(
                task_id, completed
            )
        )
        return task

    def _discard_job(self, task_id: str, completed: asyncio.Task[None]) -> None:
        with self._lock:
            if self._jobs.get(task_id) is completed:
                self._jobs.pop(task_id, None)

    async def _execute(
        self,
        task_id: str,
        operation: TaskOperation,
        timeout: float,
        desktop_exclusive: bool,
    ) -> None:
        if desktop_exclusive:
            async with self._desktop_lock:
                await self._run_operation(task_id, operation, timeout)
        else:
            await self._run_operation(task_id, operation, timeout)

    async def _run_operation(
        self, task_id: str, operation: TaskOperation, timeout: float
    ) -> None:
        try:
            self.transition(task_id, "running")
        except TaskTransitionError:
            return

        try:
            result = await asyncio.wait_for(operation(), timeout=timeout)
            if not isinstance(result, dict) or result.get("ok") is False:
                detail = (
                    result.get("error", "Executor nao confirmou sucesso.")
                    if isinstance(result, dict)
                    else "Resultado invalido do executor."
                )
                raise RuntimeError(str(detail))
        except asyncio.TimeoutError:
            self._try_terminal_transition(
                task_id, "timeout", error=f"Timeout de {timeout:g}s excedido."
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._try_terminal_transition(
                task_id,
                "failed",
                error=str(error).strip() or type(error).__name__,
            )
        else:
            self._try_terminal_transition(task_id, "completed", result=result)

    def _try_terminal_transition(
        self,
        task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        try:
            self.transition(task_id, status, result=result, error=error)
        except TaskTransitionError:
            return False
        return True

    async def cancel(
        self, task_id: str, *, error: str = "Execucao cancelada."
    ) -> dict[str, Any]:
        with self._lock:
            task = self.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task["status"] == "cancelled":
                return task
            if task["status"] in TERMINAL_STATUSES:
                raise TaskTransitionError(
                    f"Task {task_id} ja terminou com status {task['status']}."
                )
            cancelled = self.transition(task_id, "cancelled", error=error)
            job = self._jobs.get(task_id)
            if job is not None and not job.done():
                job.cancel()

        if job is not None and job is not asyncio.current_task():
            await asyncio.gather(job, return_exceptions=True)
        return cancelled

    def get(self, task_id: str) -> dict[str, Any] | None:
        if self._task_repository is not None:
            try:
                uuid_id = uuid.UUID(task_id)
            except (ValueError, AttributeError, TypeError):
                return None
            record = self._task_repository.get(uuid_id)
            return _record_to_public(record) if record is not None else None
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if self._task_repository is not None:
            records = sorted(self._task_repository.list(), key=lambda r: r.created_at)
            records = records[-max(1, min(limit, 500)):]
            return [_record_to_public(record) for record in reversed(records)]
        with self._lock:
            tasks = list(self._tasks.values())[-max(1, min(limit, 500)):]
            return [dict(task) for task in reversed(tasks)]

    def reconcile(self) -> None:
        """Recupera explicitamente o estado após um restart.

        É chamado pelo startup FastAPI, nunca por __init__: em modo arquivo,
        normaliza e persiste estados recuperados; em modo repository, executa
        a consulta e as transições necessárias no banco."""

        if self._task_repository is None:
            changed = False
            with self._lock:
                for task in self._tasks.values():
                    if "agent_id" not in task:
                        task["agent_id"] = None
                        changed = True
                    status = task.get("status")
                    if status == "queued":
                        task["status"] = "pending"
                        changed = True
                    elif status == "interrupted":
                        task["status"] = "failed"
                        task["finished_at"] = task.get("finished_at") or _now()
                        task["error"] = self._interruption_error(
                            task.get("error"),
                            "Execution interrupted by shutdown/restart.",
                        )
                        changed = True
                    elif status == "running":
                        task["status"] = "failed"
                        task["finished_at"] = _now()
                        task["error"] = self._interruption_error(
                            task.get("error"),
                            "Execution interrupted by application restart.",
                        )
                        changed = True
                if changed:
                    self._persist()
            return
        with self._lock:
            for record in self._task_repository.list(status=TaskStatus.RUNNING):
                self._task_repository.update_status(
                    record.id,
                    TaskStatus.FAILED,
                    finished_at=_utcnow(),
                    error_text=self._interruption_error(
                        record.error_text,
                        "Execution interrupted by application restart.",
                    ),
                    failure_code="interrupted_by_restart",
                )

    def summary(self) -> dict[str, Any]:
        tasks = self.list(limit=500)
        active = sum(task["status"] in ACTIVE_STATUSES for task in tasks)
        failed = sum(task["status"] in {"failed", "timeout"} for task in tasks)
        active_tasks = [task for task in tasks if task["status"] in ACTIVE_STATUSES]
        executors = {str(task.get("executor") or "local").casefold() for task in active_tasks}
        executor = "idle" if not executors else next(iter(executors)) if len(executors) == 1 else "multi"
        last = tasks[0] if tasks else None
        last_task = (
            {
                key: last.get(key)
                for key in (
                    "task_id",
                    "type",
                    "status",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "agent_id",
                )
            }
            if last is not None
            else None
        )
        return {
            "tasks": active,
            "total": len(tasks),
            "failed": failed,
            "executor": executor,
            "last_task": last_task,
            "active_tasks": [
                {key: task.get(key) for key in ("task_id", "type", "status", "created_at", "started_at", "finished_at", "executor", "display_name", "agent_id")}
                for task in active_tasks
            ],
        }

    async def wait(
        self, task_id: str, timeout: float | None = None
    ) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(task_id)
        if job is not None:
            await asyncio.wait_for(asyncio.shield(job), timeout=timeout)
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    async def shutdown(self) -> None:
        with self._lock:
            if self._task_repository is not None:
                active_records = self._task_repository.list(
                    status=TaskStatus.PENDING
                ) + self._task_repository.list(status=TaskStatus.RUNNING)
                task_ids = [record.id.hex for record in active_records]
            else:
                task_ids = [
                    task_id
                    for task_id, task in self._tasks.items()
                    if task.get("status") in ACTIVE_STATUSES
                ]
        for task_id in task_ids:
            try:
                await self.cancel(
                    task_id,
                    error="Execucao interrompida durante o shutdown do Jarvis.",
                )
            except (KeyError, TaskTransitionError):
                continue
