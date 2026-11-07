"""Paridade Python para arquivos, desktop, browser, workflow e Excel."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.automation.excel import create_workbook, read_workbook
from app.core.config import PROJECT_ROOT


router = APIRouter(prefix="/api", tags=["automation"])
SYSTEM_DIR = PROJECT_ROOT / "system"
PROJECTS_DIR = PROJECT_ROOT / "Documents and Projects"
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".js", ".ts", ".py", ".html", ".css", ".csv", ".xml", ".sql", ".sh", ".bat", ".ps1"}


def _allowed_path(raw_path: str, *, must_exist: bool = True) -> Path:
    path = Path(raw_path).expanduser().resolve()
    roots = (PROJECT_ROOT.resolve(), Path.home().resolve())
    if not any(path == root or root in path.parents for root in roots):
        raise HTTPException(status_code=403, detail="Caminho fora das areas autorizadas.")
    if must_exist and not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")
    return path


async def _run_script(
    name: str,
    args: list[str] | None = None,
    *,
    stdin_payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    command = [sys.executable, str(SYSTEM_DIR / name), *(args or [])]
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(PROJECT_ROOT),
        stdin=asyncio.subprocess.PIPE if stdin_payload is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    input_bytes = json.dumps(stdin_payload, ensure_ascii=False).encode("utf-8") if stdin_payload is not None else None
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(input_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail=f"Executor excedeu timeout de {timeout:g}s.")
    return process.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _last_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise HTTPException(status_code=500, detail="Executor nao retornou JSON valido.")


# ---------------------------------------------------------------------------
# Security policy (2026-09-05, decisao arquitetural do usuario — ver
# JARVIS_MASTER.md secao de seguranca):
#
#   ARBITRARY SHELL VIA API      = FORBIDDEN
#   ARBITRARY JAVASCRIPT VIA API = FORBIDDEN
#   BROWSER AUTOMATION           = ALLOWED THROUGH BOUNDED OPERATIONS
#
# Estes dois allowlists sao a metade desta decisao aplicada na fronteira da
# API (defesa em profundidade — system/ui-automation.py e
# system/browser-control.py aplicam a mesma decisao na camada do script,
# removendo de vez as funcoes "action_shell"/"cmd_execute_js"; isto aqui NAO
# e uma segunda policy paralela, e uma checagem estrutural de QUAIS nomes de
# acao/comando podem sequer chegar la — o conteudo de uma URL de navegacao,
# por exemplo, continua validado so em system/browser-control.py).
# ---------------------------------------------------------------------------

_SAFE_WORKFLOW_ACTION_TYPES = frozenset(
    {
        "app_focus",
        "app_close",
        "app_minimize",
        "app_maximize",
        "key",
        "type",
        "click",
        "scroll",
        "wait",
        "wait_for",
        "screenshot",
        "uia_click",
        "uia_set_value",
        "uia_get_text",
        "uia_tree",
    }
)

_SAFE_BROWSER_CONTROL_COMMANDS = frozenset(
    {
        "connect",
        "list_tabs",
        "navigate",
        "get_dom",
        "click",
        "fill",
        "get_text",
        "wait_for",
        "screenshot",
    }
)


def _validate_workflow_actions(actions: list[Any]) -> str | None:
    """Retorna uma mensagem de erro se alguma action nao estiver no
    allowlist bounded, ou None se todas forem seguras. Nenhuma action do
    tipo "shell"/exec/eval passa por aqui, seja qual for o nome usado."""

    for action in actions:
        if not isinstance(action, dict):
            return "cada action deve ser um objeto."
        action_type = action.get("type")
        if action_type not in _SAFE_WORKFLOW_ACTION_TYPES:
            return f"action type nao permitido: {action_type!r}."
    return None


def _validate_browser_control_cmd(cmd: str) -> str | None:
    """Retorna uma mensagem de erro se o comando nao estiver no allowlist
    bounded (em particular, "execute_js" nunca passa por aqui), ou None."""

    if cmd not in _SAFE_BROWSER_CONTROL_COMMANDS:
        return f"comando nao permitido: {cmd!r}."
    return None


@router.get("/read-file")
async def read_file(path: str = Query(...)) -> dict[str, object]:
    file_path = _allowed_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="O caminho nao e um arquivo.")
    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
        return {"binary": True, "path": str(file_path), "size": file_path.stat().st_size}
    try:
        content = await asyncio.to_thread(file_path.read_text, encoding="utf-8")
    except UnicodeDecodeError:
        return {"binary": True, "path": str(file_path), "size": file_path.stat().st_size}
    return {"content": content, "size": len(content), "lines": len(content.splitlines()), "path": str(file_path)}


@router.get("/find-file")
async def find_file(name: str = Query(..., min_length=1)) -> dict[str, object]:
    needle = name.casefold()
    roots = [PROJECTS_DIR, Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]

    def search() -> list[str]:
        found: list[str] = []
        for root in roots:
            if not root.is_dir():
                continue
            try:
                for item in root.rglob("*"):
                    if len(item.relative_to(root).parts) > 4:
                        continue
                    if item.is_file() and needle in item.name.casefold():
                        found.append(str(item))
                        if len(found) == 10:
                            return found
            except (OSError, PermissionError):
                continue
        return found

    return {"found": await asyncio.to_thread(search)}


@router.post("/files/search")
async def files_search(request: Request) -> dict[str, object]:
    payload = await request.json()
    command = str(payload.get("cmd") or "search")
    args = [command]
    if command == "search":
        args.append(str(payload.get("query") or ""))
    elif command == "recent":
        args.append(str(payload.get("days") or 7))
    elif command == "large":
        args.append(str(payload.get("mb") or 100))
    elif command == "organize":
        path = _allowed_path(str(payload.get("path") or ""))
        args.append(str(path))
    else:
        raise HTTPException(status_code=400, detail="Comando de arquivos invalido.")
    code, stdout, stderr = await _run_script("file-index.py", args, timeout=30)
    if code:
        raise HTTPException(status_code=500, detail=stderr.strip() or "Falha na busca de arquivos.")
    return _last_json(stdout)


@router.post("/excel-live")
async def excel_live(request: Request) -> dict[str, object]:
    payload = await request.json()
    action = str(payload.get("action") or "read")
    if action == "create":
        return await create_workbook(payload)
    if action == "read":
        if not payload.get("path"):
            raise HTTPException(status_code=400, detail="path required")
        return await read_workbook(str(payload["path"]), payload.get("sheet"), formulas=False)
    if action == "list":
        import psutil
        running = any(proc.info.get("name", "").upper() == "EXCEL.EXE" for proc in psutil.process_iter(["name"]))
        return {"excel_running": running}
    raise HTTPException(status_code=400, detail="Acao Excel suportada: create, read, list.")


@router.post("/read-excel")
async def read_excel(request: Request) -> dict[str, object]:
    payload = await request.json()
    if not payload.get("path"):
        raise HTTPException(status_code=400, detail="path required")
    return await read_workbook(str(payload["path"]), payload.get("sheet"), formulas=bool(payload.get("formulas")))


@router.get("/screenshot")
async def screenshot(monitor: str = "1") -> dict[str, object]:
    code, stdout, stderr = await _run_script("screenshot.py", [monitor], timeout=15)
    if code:
        raise HTTPException(status_code=500, detail=stderr.strip() or "Screenshot failed.")
    return _last_json(stdout)


@router.get("/screen-state")
async def screen_state() -> dict[str, object]:
    module_path = SYSTEM_DIR / "screen-state.py"

    def snapshot() -> dict[str, object]:
        spec = importlib.util.spec_from_file_location("jarvis_screen_state", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Modulo screen-state indisponivel.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return dict(module.take_snapshot())

    return await asyncio.to_thread(snapshot)


@router.get("/clipboard")
async def clipboard() -> dict[str, object]:
    try:
        import pyperclip
        text = await asyncio.to_thread(pyperclip.paste)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Clipboard indisponivel: {error}")
    return {"clipboard": text, "analysis": {"type": "text", "length": len(text)} if text else None}


async def _task_for_script(request: Request, task_type: str, description: str, script: str, *, args: list[str] | None = None, stdin: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, object]:
    async def operation() -> dict[str, Any]:
        code, stdout, stderr = await _run_script(script, args, stdin_payload=stdin, timeout=timeout)
        if code:
            return {"ok": False, "error": stderr.strip() or stdout.strip() or f"exit code {code}"}
        result = _last_json(stdout)
        if "ok" not in result:
            result["ok"] = result.get("success", True) is not False
        return result

    task = request.app.state.task_manager.submit(task_type, description, operation, timeout=timeout + 2, desktop_exclusive=True)
    return task


@router.post("/computer-use", status_code=202)
async def computer_use(request: Request) -> dict[str, object]:
    payload = await request.json()
    return await _task_for_script(request, "computer.action", str(payload.get("action") or "Desktop action"), "computer-action.py", args=[json.dumps(payload, ensure_ascii=False)], timeout=10)


@router.post("/computer-use/task", status_code=202)
@router.post("/computer-use/v2", status_code=202)
async def computer_use_task(request: Request) -> dict[str, object]:
    payload = await request.json()
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise HTTPException(status_code=400, detail="actions explicitas sao obrigatorias; planejamento por IA nao e presumido.")
    validation_error = _validate_workflow_actions(actions)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    return await _task_for_script(request, "computer.workflow", str(payload.get("task") or "Desktop workflow"), "ui-automation.py", stdin={"actions": actions}, timeout=90)


@router.post("/browser-control")
async def browser_control(request: Request) -> dict[str, object]:
    payload = await request.json()
    cmd = str(payload.get("cmd") or "")
    validation_error = _validate_browser_control_cmd(cmd)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    code, stdout, stderr = await _run_script("browser-control.py", ["--auto-connect"], stdin_payload=payload, timeout=15)
    if code:
        raise HTTPException(status_code=500, detail=stderr.strip() or "Browser control failed.")
    return _last_json(stdout)


@router.post("/workflow", status_code=202)
async def workflow(request: Request) -> dict[str, object]:
    payload = await request.json()
    if isinstance(payload.get("actions"), list) and payload["actions"]:
        validation_error = _validate_workflow_actions(payload["actions"])
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)
        return await _task_for_script(request, "workflow", str(payload.get("name") or "Workflow"), "ui-automation.py", stdin={"actions": payload["actions"]}, timeout=120)
    action = str(payload.get("action") or "")
    if action == "list":
        code, stdout, stderr = await _run_script("workflow-recorder.py", ["list"], timeout=5)
        return {"ok": code == 0, "output": stdout, "error": stderr or None}
    raise HTTPException(status_code=400, detail="actions ou action=list required.")


@router.post("/pdf")
async def pdf_unavailable() -> None:
    raise HTTPException(status_code=501, detail="Geracao PDF ainda requer migracao Python sem nova dependencia.")
