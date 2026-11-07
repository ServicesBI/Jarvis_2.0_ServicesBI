"""Action bounded para abrir arquivos nas subroots oficiais autorizadas."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.actions.app_open import ExecutableResolution, _validate_resolution, process_ids_for, resolve_application
from app.actions.models import ActionArtifact, ActionResult, ActionRisk, PersistencePolicy
from app.actions.policy import PathAccess, PathPolicy
from app.actions.registry import ActionDefinition
from app.core.config import EXCEL_WORKSPACE, POWERBI_WORKSPACE, WORD_WORKSPACE


EXTENSION_APPLICATIONS: dict[str, str] = {
    ".docx": "word",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".pbix": "powerbi",
}

EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pbix": "application/x-power-bi",
}


class FileOpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)


Resolver = Callable[[str], ExecutableResolution]
Launcher = Callable[[Path, Path], object]
ProcessSnapshot = Callable[[ExecutableResolution], set[int]]
Sleeper = Callable[[float], Awaitable[None]]


def _reject_network_or_device_path(raw_path: str) -> None:
    if raw_path.strip().replace("/", "\\").startswith("\\\\"):
        raise PermissionError("Caminhos de rede ou dispositivo nao sao permitidos.")


def application_for_file(path: Path) -> str:
    application = EXTENSION_APPLICATIONS.get(path.suffix.casefold())
    if application is None:
        raise ValueError("Extensao de arquivo nao permitida para file.open.")
    return application


def workspace_for_file(
    path: str | Path,
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
) -> Path:
    extension = Path(path).suffix.casefold()
    roots = {
        ".docx": word_workspace or WORD_WORKSPACE,
        ".xlsx": excel_workspace or EXCEL_WORKSPACE,
        ".xlsm": excel_workspace or EXCEL_WORKSPACE,
        ".pbix": powerbi_workspace or POWERBI_WORKSPACE,
    }
    try:
        return Path(roots[extension]).resolve()
    except KeyError as error:
        raise ValueError("Extensao de arquivo nao permitida para file.open.") from error


def validate_file_path(
    raw_path: str | Path,
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
    path_policy: PathPolicy | None = None,
) -> Path:
    raw_text = str(raw_path).strip()
    _reject_network_or_device_path(raw_text)
    root = workspace_for_file(
        raw_text,
        word_workspace=word_workspace,
        excel_workspace=excel_workspace,
        powerbi_workspace=powerbi_workspace,
    )
    candidate = Path(raw_text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    policy = path_policy or PathPolicy(read_roots=(root,))
    resolved = policy.validate(candidate, access=PathAccess.READ)
    if not resolved.is_file():
        raise IsADirectoryError("O caminho autorizado deve apontar para um arquivo regular.")
    application_for_file(resolved)
    return resolved


def launch_file(executable: Path, file_path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(executable.resolve()), str(file_path.resolve())],
        shell=False,
        close_fds=True,
    )


def create_file_open_definition(
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
    resolver: Resolver = resolve_application,
    launcher: Launcher = launch_file,
    process_snapshot: ProcessSnapshot = process_ids_for,
    sleeper: Sleeper = asyncio.sleep,
    verification_attempts: int = 10,
    verification_delay: float = 0.2,
) -> ActionDefinition:
    pending: dict[str, tuple[Path, Path, ExecutableResolution]] = {}

    async def handler(arguments: FileOpenInput) -> ActionResult:
        file_path = validate_file_path(
            arguments.path,
            word_workspace=word_workspace,
            excel_workspace=excel_workspace,
            powerbi_workspace=powerbi_workspace,
        )
        root = workspace_for_file(
            file_path,
            word_workspace=word_workspace,
            excel_workspace=excel_workspace,
            powerbi_workspace=powerbi_workspace,
        )
        application = application_for_file(file_path)
        resolution = resolver(application)
        executable = _validate_resolution(resolution)
        launcher(executable, file_path)
        relative_path = file_path.relative_to(root).as_posix()
        pending[relative_path] = (file_path, root, resolution)
        return ActionResult(
            ok=True,
            action="file.open",
            summary=f"Solicitacao de abertura de {file_path.name} executada.",
            artifacts=[ActionArtifact(path=relative_path, exists=True, size=file_path.stat().st_size, media_type=EXTENSION_MEDIA_TYPES[file_path.suffix.casefold()])],
            data={"application": application, "file": relative_path, "process_detected": False},
        )

    async def verifier(arguments: FileOpenInput, result: ActionResult) -> bool:
        relative_path = str(result.data.get("file") or "")
        state = pending.pop(relative_path, None)
        if state is None:
            return False
        file_path, root, resolution = state
        try:
            current = validate_file_path(
                file_path,
                word_workspace=word_workspace,
                excel_workspace=excel_workspace,
                powerbi_workspace=powerbi_workspace,
                path_policy=PathPolicy(read_roots=(root,)),
            )
            _validate_resolution(resolution)
        except (OSError, ValueError):
            return False
        if current != file_path or len(result.artifacts) != 1:
            return False
        artifact = result.artifacts[0]
        if artifact.path != relative_path or not artifact.exists or artifact.size != file_path.stat().st_size:
            return False
        for attempt in range(max(1, verification_attempts)):
            if process_snapshot(resolution):
                result.data["process_detected"] = True
                return True
            if attempt + 1 < max(1, verification_attempts):
                await sleeper(max(0.0, verification_delay))
        return False

    return ActionDefinition(
        name="file.open",
        description="Abrir arquivo autorizado na subroot oficial correspondente",
        input_model=FileOpenInput,
        handler=handler,
        verifier=verifier,
        risk=ActionRisk.DESKTOP,
        confirmation_required=False,
        timeout=15.0,
        desktop_exclusive=True,
        persistence=PersistencePolicy.SANITIZED,
        allowed_sources=frozenset({"chat", "api"}),
    )
