"""Abertura bounded de PBIX pela associacao oficial do Windows."""
from __future__ import annotations
import asyncio
import ctypes
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import psutil

Launcher = Callable[[Path], object]
Sleeper = Callable[[float], Awaitable[None]]

class PowerBIDesktopStatus(str, Enum):
    OPENED = "opened"
    ALREADY_OPEN = "already_open"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class DesktopWindow:
    pid: int
    handle: int
    title: str
    visible: bool
    responding: bool

@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    pids: frozenset[int]
    windows: tuple[DesktopWindow, ...]

@dataclass(frozen=True, slots=True)
class PowerBIDesktopOpenResult:
    status: PowerBIDesktopStatus
    launch_requested: bool
    process_detected: bool
    report_loaded: bool
    pid: int | None = None
    window_handle: int | None = None
    method: str = "windows_file_association"
    error_code: str | None = None

    @property
    def opened(self) -> bool:
        return self.status in {PowerBIDesktopStatus.OPENED, PowerBIDesktopStatus.ALREADY_OPEN}

def _launch_associated_pbix(file_path: Path) -> None:
    os.startfile(str(file_path))

def powerbi_process_ids() -> set[int]:
    found: set[int] = set()
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name") or "").casefold() == "pbidesktop.exe":
                found.add(int(process.info["pid"]))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue
    return found

def powerbi_desktop_snapshot() -> DesktopSnapshot:
    pids = powerbi_process_ids()
    if os.name != "nt":
        return DesktopSnapshot(frozenset(pids), ())
    windows: list[DesktopWindow] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    @callback_type
    def collect(handle: int, _parameter: int) -> bool:
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        pid = int(process_id.value)
        if pid not in pids:
            return True
        length = user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        if length > 0:
            user32.GetWindowTextW(handle, buffer, length + 1)
        response = ctypes.c_ulong()
        responding = bool(user32.SendMessageTimeoutW(handle, 0, 0, 0, 0x0002, 100, ctypes.byref(response)))
        windows.append(DesktopWindow(pid, int(handle), buffer.value.strip(), bool(user32.IsWindowVisible(handle)), responding))
        return True
    user32.EnumWindows(collect, 0)
    return DesktopSnapshot(frozenset(pids), tuple(windows))

def _normalized_title(title: str) -> str:
    value = title.strip().casefold()
    suffix = " - power bi desktop"
    return value[:-len(suffix)].strip() if value.endswith(suffix) else value

def _matching_window(snapshot: DesktopSnapshot, expected: str) -> DesktopWindow | None:
    return next((w for w in snapshot.windows if w.handle and w.visible and w.responding and _normalized_title(w.title) == expected), None)

async def open_powerbi_desktop(file_path: Path, *, launcher: Launcher = _launch_associated_pbix,
    snapshot: Callable[[], DesktopSnapshot] = powerbi_desktop_snapshot,
    sleeper: Sleeper = asyncio.sleep, timeout: float = 90.0,
    verification_delay: float = 0.5) -> PowerBIDesktopOpenResult:
    try:
        pbix = Path(file_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return PowerBIDesktopOpenResult(PowerBIDesktopStatus.FAILED, False, False, False, error_code="invalid_file")
    if not pbix.is_file() or pbix.suffix.casefold() != ".pbix":
        return PowerBIDesktopOpenResult(PowerBIDesktopStatus.FAILED, False, False, False, error_code="invalid_file")
    expected = pbix.stem.casefold()
    try:
        before = snapshot()
    except (OSError, RuntimeError):
        before = DesktopSnapshot(frozenset(), ())
    existing = _matching_window(before, expected)
    if existing:
        return PowerBIDesktopOpenResult(PowerBIDesktopStatus.ALREADY_OPEN, False, True, True, existing.pid, existing.handle)
    try:
        launcher(pbix)
    except OSError:
        return PowerBIDesktopOpenResult(PowerBIDesktopStatus.FAILED, False, bool(before.pids), False, error_code="launch_failed")
    elapsed = 0.0
    process_detected = bool(before.pids)
    delay = max(0.01, verification_delay)
    while elapsed < max(0.0, timeout):
        try:
            current = snapshot()
            process_detected = process_detected or bool(current.pids)
            ready = _matching_window(current, expected)
        except (OSError, RuntimeError):
            ready = None
        if ready:
            return PowerBIDesktopOpenResult(PowerBIDesktopStatus.OPENED, True, True, True, ready.pid, ready.handle)
        sleep_for = min(delay, timeout - elapsed)
        if sleep_for <= 0:
            break
        await sleeper(sleep_for)
        elapsed += sleep_for
    return PowerBIDesktopOpenResult(PowerBIDesktopStatus.FAILED, True, process_detected, False, error_code="report_not_loaded")
