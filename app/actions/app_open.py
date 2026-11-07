"""Action bounded para abrir aplicativos Desktop explicitamente allowlisted."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psutil
from pydantic import BaseModel, ConfigDict

from app.actions.models import ActionResult, ActionRisk, PersistencePolicy
from app.actions.registry import ActionDefinition


ApplicationName = Literal["vscode", "word", "excel", "powerbi"]

EXPECTED_EXECUTABLES: dict[str, str] = {
    "vscode": "Code.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerbi": "PBIDesktop.exe",
}


class AppOpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application: ApplicationName


@dataclass(frozen=True, slots=True)
class ExecutableResolution:
    application: str
    executable: Path
    method: str


RegistryLookup = Callable[[str], Path | None]
KnownPaths = Callable[[str], Iterable[Path]]
TrustedRoots = Callable[[str], Iterable[Path]]
WhichLookup = Callable[[str], str | None]
Resolver = Callable[[str], ExecutableResolution]
Launcher = Callable[[Path], object]
ProcessSnapshot = Callable[[ExecutableResolution], set[int]]
Sleeper = Callable[[float], Awaitable[None]]


def _registry_app_path(executable_name: str) -> Path | None:
    try:
        import winreg
    except ImportError:
        return None

    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    views = tuple(
        flag
        for flag in (
            getattr(winreg, "KEY_WOW64_64KEY", 0),
            getattr(winreg, "KEY_WOW64_32KEY", 0),
        )
        if flag or len({getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)}) == 1
    ) or (0,)
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                return Path(os.path.expandvars(value.strip().strip('"')))
    return None


def _known_application_paths(application: str) -> tuple[Path, ...]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", ""))
    roots = tuple(root for root in (program_files, program_files_x86) if str(root))
    if application == "vscode":
        return (
            local / "Programs" / "Microsoft VS Code" / "Code.exe",
            *(root / "Microsoft VS Code" / "Code.exe" for root in roots),
        )
    if application in {"word", "excel"}:
        executable = EXPECTED_EXECUTABLES[application]
        return tuple(
            root / "Microsoft Office" / "root" / version / executable
            for root in roots
            for version in ("Office16", "Office15")
        )
    if application == "powerbi":
        return tuple(
            root / "Microsoft Power BI Desktop" / "bin" / "PBIDesktop.exe"
            for root in roots
        )
    return ()


def _trusted_application_roots(application: str) -> tuple[Path, ...]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", ""))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", ""))
    roots = tuple(root for root in (program_files, program_files_x86) if str(root))
    if application == "vscode":
        return (
            local / "Programs" / "Microsoft VS Code",
            *(root / "Microsoft VS Code" for root in roots),
        )
    if application in {"word", "excel"}:
        return tuple(root / "Microsoft Office" for root in roots)
    if application == "powerbi":
        return tuple(root / "Microsoft Power BI Desktop" for root in roots)
    return ()


def _safe_executable(
    path: Path | str | None,
    expected_name: str,
    *,
    trusted_roots: Iterable[Path] | None = None,
) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser().resolve()
    allowed_roots = (
        tuple(Path(root).expanduser().resolve() for root in trusted_roots)
        if trusted_roots is not None
        else ()
    )
    if (
        candidate.name.casefold() != expected_name.casefold()
        or candidate.suffix.casefold() != ".exe"
        or not candidate.is_file()
        or (
            trusted_roots is not None
            and not any(candidate == root or root in candidate.parents for root in allowed_roots)
        )
    ):
        return None
    return candidate


def resolve_application(
    application: str,
    *,
    registry_lookup: RegistryLookup | None = None,
    known_paths: KnownPaths | None = None,
    which: WhichLookup | None = None,
    trusted_roots: TrustedRoots | None = None,
) -> ExecutableResolution:
    expected_name = EXPECTED_EXECUTABLES.get(application)
    if expected_name is None:
        raise ValueError("Aplicativo fora da allowlist.")
    registry = registry_lookup or _registry_app_path
    candidates = known_paths or _known_application_paths
    which_lookup = which or shutil.which
    roots = tuple((trusted_roots or _trusted_application_roots)(application))

    resolved = _safe_executable(
        registry(expected_name), expected_name, trusted_roots=roots
    )
    if resolved is not None:
        return ExecutableResolution(application, resolved, "registry_app_paths")
    for candidate in candidates(application):
        resolved = _safe_executable(candidate, expected_name, trusted_roots=roots)
        if resolved is not None:
            return ExecutableResolution(application, resolved, "known_path")
    resolved = _safe_executable(
        which_lookup(expected_name), expected_name, trusted_roots=roots
    )
    if resolved is not None:
        return ExecutableResolution(application, resolved, "path")
    raise FileNotFoundError(f"Executavel de {application} nao encontrado.")


def _validate_resolution(resolution: ExecutableResolution) -> Path:
    expected_name = EXPECTED_EXECUTABLES.get(resolution.application)
    executable = _safe_executable(resolution.executable, expected_name or "")
    if executable is None:
        raise ValueError("Resolucao de aplicativo invalida.")
    return executable


def launch_application(executable: Path) -> subprocess.Popen[bytes]:
    safe_executable = executable.resolve()
    return subprocess.Popen(
        [str(safe_executable)],
        shell=False,
        close_fds=True,
    )


def process_ids_for(resolution: ExecutableResolution) -> set[int]:
    expected_name = EXPECTED_EXECUTABLES.get(resolution.application, "").casefold()
    found: set[int] = set()
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = str(process.info.get("name") or "").casefold()
            executable = process.info.get("exe")
            if name != expected_name:
                continue
            if executable and Path(str(executable)).name.casefold() != expected_name:
                continue
            found.add(int(process.info["pid"]))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue
    return found


def create_app_open_definition(
    *,
    resolver: Resolver | None = None,
    launcher: Launcher | None = None,
    process_snapshot: ProcessSnapshot | None = None,
    sleeper: Sleeper = asyncio.sleep,
    verification_attempts: int = 10,
    verification_delay: float = 0.2,
) -> ActionDefinition:
    resolve = resolver or resolve_application
    launch = launcher or launch_application
    snapshot = process_snapshot or process_ids_for
    pending: dict[str, ExecutableResolution] = {}

    async def handler(arguments: AppOpenInput) -> ActionResult:
        resolution = resolve(arguments.application)
        executable = _validate_resolution(resolution)
        before = snapshot(resolution)
        launch(executable)
        pending[arguments.application] = resolution
        return ActionResult(
            ok=True,
            action="app.open",
            summary=f"Solicitacao de abertura de {arguments.application} executada.",
            data={
                "application": arguments.application,
                "launched": True,
                "process_detected": False,
                "process_preexisting": bool(before),
                "executable_name": executable.name,
            },
        )

    async def verifier(arguments: AppOpenInput, result: ActionResult) -> bool:
        resolution = pending.pop(arguments.application, None)
        if resolution is None:
            return False
        try:
            _validate_resolution(resolution)
        except (OSError, ValueError):
            return False
        for attempt in range(max(1, verification_attempts)):
            if snapshot(resolution):
                result.data["process_detected"] = True
                return True
            if attempt + 1 < max(1, verification_attempts):
                await sleeper(max(0.0, verification_delay))
        return False

    return ActionDefinition(
        name="app.open",
        description="Abrir aplicativo allowlisted",
        input_model=AppOpenInput,
        handler=handler,
        verifier=verifier,
        risk=ActionRisk.DESKTOP,
        confirmation_required=False,
        timeout=15.0,
        desktop_exclusive=True,
        persistence=PersistencePolicy.SANITIZED,
        allowed_sources=frozenset({"chat", "api"}),
    )
