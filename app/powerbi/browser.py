"""Bounded internal service for dispatching canonical Power BI links to Chrome.

``OPENED`` means only that a validated canonical URL was delivered to a
validated Chrome executable without a launch error. It does not prove that a
tab rendered, that a report loaded, or that the user is authenticated.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psutil


CHROME_EXECUTABLE = "chrome.exe"
POWERBI_HOST = "app.powerbi.com"


class BrowserOpenOutcome(str, Enum):
    OPENED = "OPENED"
    CHROME_UNAVAILABLE = "CHROME_UNAVAILABLE"
    INVALID_LINK = "INVALID_LINK"
    LAUNCH_FAILED = "LAUNCH_FAILED"


@dataclass(frozen=True, slots=True)
class ChromeResolution:
    executable: Path
    method: str


@dataclass(frozen=True, slots=True)
class BrowserOpenResult:
    outcome: BrowserOpenOutcome
    browser: str = "chrome"
    launch_requested: bool = False
    process_detected: bool = False
    process_preexisting: bool = False
    verification_limited: bool = True
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "browser": self.browser,
            "launch_requested": self.launch_requested,
            "process_detected": self.process_detected,
            "process_preexisting": self.process_preexisting,
            "verification_limited": self.verification_limited,
            "error_code": self.error_code,
        }


RegistryLookup = Callable[[str], Path | None]
KnownPaths = Callable[[], Iterable[Path]]
WhichLookup = Callable[[str], str | None]
TrustedRoots = Callable[[], Iterable[Path]]
ChromeResolver = Callable[[], ChromeResolution]
ChromeLauncher = Callable[[Path, str], object]
ProcessSnapshot = Callable[[], set[int]]


def build_powerbi_report_url(workspace_id: UUID, report_id: UUID) -> str:
    """Build the only URL shape accepted by this service."""

    if not isinstance(workspace_id, UUID) or not isinstance(report_id, UUID):
        raise ValueError("Invalid Power BI link identifiers.")
    url = (
        f"https://{POWERBI_HOST}/groups/{workspace_id}/reports/{report_id}"
    )
    return _validate_powerbi_report_url(url, workspace_id, report_id)


def validate_publish_to_web_src(source: object) -> str:
    if not isinstance(source, str) or not source or source != source.strip():
        raise ValueError("Invalid Publish to Web URL.")
    try:
        parsed = urlsplit(source)
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("Invalid Publish to Web URL.") from None
    if (parsed.scheme != "https" or parsed.netloc != POWERBI_HOST or port is not None
            or parsed.username is not None or parsed.password is not None
            or parsed.path != "/view" or not parsed.query.startswith("r=") or parsed.fragment):
        raise ValueError("Invalid Publish to Web URL.")
    return source


def _validate_powerbi_report_url(
    url: str, workspace_id: UUID, report_id: UUID
) -> str:
    if not isinstance(workspace_id, UUID) or not isinstance(report_id, UUID):
        raise ValueError("Invalid Power BI link identifiers.")
    if not isinstance(url, str):
        raise ValueError("Invalid Power BI URL.")

    expected_path = f"/groups/{workspace_id}/reports/{report_id}"
    expected_url = f"https://{POWERBI_HOST}{expected_path}"
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("Invalid Power BI URL.") from None

    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != POWERBI_HOST
        or parsed.netloc.casefold() != POWERBI_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid Power BI URL.")
    return expected_url


def _trusted_chrome_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for environment_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(environment_name)
        if base:
            roots.append(Path(base) / "Google" / "Chrome" / "Application")
    return tuple(roots)


def _known_chrome_paths() -> tuple[Path, ...]:
    return tuple(root / CHROME_EXECUTABLE for root in _trusted_chrome_roots())


def _registry_chrome_path(executable_name: str) -> Path | None:
    try:
        import winreg
    except ImportError:
        return None

    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    views = tuple(
        dict.fromkeys(
            (
                getattr(winreg, "KEY_WOW64_64KEY", 0),
                getattr(winreg, "KEY_WOW64_32KEY", 0),
            )
        )
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in views:
            try:
                with winreg.OpenKey(
                    hive, subkey, 0, winreg.KEY_READ | view
                ) as registry_key:
                    value, _ = winreg.QueryValueEx(registry_key, None)
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                return Path(os.path.expandvars(value.strip().strip('"')))
    return None


def _safe_chrome_executable(
    candidate: Path | str | None, trusted_roots: Iterable[Path]
) -> Path | None:
    if candidate is None:
        return None
    try:
        executable = Path(candidate).expanduser().resolve()
        roots = tuple(Path(root).expanduser().resolve() for root in trusted_roots)
    except (OSError, RuntimeError):
        return None
    if (
        executable.name.casefold() != CHROME_EXECUTABLE
        or executable.suffix.casefold() != ".exe"
        or not executable.is_file()
        or not any(executable == root or root in executable.parents for root in roots)
    ):
        return None
    return executable


def resolve_chrome(
    *,
    registry_lookup: RegistryLookup | None = None,
    known_paths: KnownPaths | None = None,
    which: WhichLookup | None = None,
    trusted_roots: TrustedRoots | None = None,
) -> ChromeResolution:
    """Resolve Chrome through bounded sources and one final trust policy."""

    registry = registry_lookup or _registry_chrome_path
    known = known_paths or _known_chrome_paths
    which_lookup = which or shutil.which
    roots = tuple((trusted_roots or _trusted_chrome_roots)())

    executable = _safe_chrome_executable(registry(CHROME_EXECUTABLE), roots)
    if executable is not None:
        return ChromeResolution(executable=executable, method="registry_app_paths")
    for candidate in known():
        executable = _safe_chrome_executable(candidate, roots)
        if executable is not None:
            return ChromeResolution(executable=executable, method="known_path")
    executable = _safe_chrome_executable(which_lookup(CHROME_EXECUTABLE), roots)
    if executable is not None:
        return ChromeResolution(executable=executable, method="path")
    raise FileNotFoundError("Trusted Chrome executable not found.")


def _launch_chrome(executable: Path, canonical_url: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(executable), canonical_url],
        shell=False,
        close_fds=True,
    )


def chrome_process_ids() -> set[int]:
    found: set[int] = set()
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if str(process.info.get("name") or "").casefold() != CHROME_EXECUTABLE:
                continue
            process_executable = process.info.get("exe")
            if process_executable and Path(str(process_executable)).name.casefold() != CHROME_EXECUTABLE:
                continue
            found.add(int(process.info["pid"]))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue
    return found


def open_powerbi_report(
    workspace_id: UUID,
    report_id: UUID,
    *,
    resolver: ChromeResolver | None = None,
    launcher: ChromeLauncher | None = None,
    process_snapshot: ProcessSnapshot | None = None,
    trusted_roots: TrustedRoots | None = None,
) -> BrowserOpenResult:
    """Dispatch a derived canonical report URL without claiming visual proof."""

    try:
        canonical_url = build_powerbi_report_url(workspace_id, report_id)
    except ValueError:
        return BrowserOpenResult(
            outcome=BrowserOpenOutcome.INVALID_LINK, error_code="invalid_link"
        )

    resolve = resolver or resolve_chrome
    roots = tuple((trusted_roots or _trusted_chrome_roots)())
    try:
        resolution = resolve()
        executable = _safe_chrome_executable(resolution.executable, roots)
        if executable is None:
            raise FileNotFoundError
    except (FileNotFoundError, OSError, ValueError):
        return BrowserOpenResult(
            outcome=BrowserOpenOutcome.CHROME_UNAVAILABLE,
            error_code="chrome_unavailable",
        )

    snapshot = process_snapshot or chrome_process_ids
    try:
        before = snapshot()
    except (OSError, RuntimeError):
        before = set()

    try:
        canonical_url = _validate_powerbi_report_url(
            canonical_url, workspace_id, report_id
        )
        (launcher or _launch_chrome)(executable, canonical_url)
    except (OSError, subprocess.SubprocessError, ValueError):
        error_code = "invalid_link" if not _is_valid_link(canonical_url, workspace_id, report_id) else "launch_failed"
        outcome = (
            BrowserOpenOutcome.INVALID_LINK
            if error_code == "invalid_link"
            else BrowserOpenOutcome.LAUNCH_FAILED
        )
        return BrowserOpenResult(outcome=outcome, error_code=error_code)

    try:
        after = snapshot()
    except (OSError, RuntimeError):
        after = set()
    return BrowserOpenResult(
        outcome=BrowserOpenOutcome.OPENED,
        launch_requested=True,
        process_detected=bool(after),
        process_preexisting=bool(before),
    )


def _is_valid_link(url: object, workspace_id: object, report_id: object) -> bool:
    try:
        _validate_powerbi_report_url(url, workspace_id, report_id)  # type: ignore[arg-type]
    except ValueError:
        return False
    return True


def open_powerbi_publish_to_web(
    source: str, *, resolver: ChromeResolver | None = None,
    launcher: ChromeLauncher | None = None,
    process_snapshot: ProcessSnapshot | None = None,
    trusted_roots: TrustedRoots | None = None,
) -> BrowserOpenResult:
    try:
        exact_source = validate_publish_to_web_src(source)
    except ValueError:
        return BrowserOpenResult(BrowserOpenOutcome.INVALID_LINK, error_code="invalid_link")
    resolve = resolver or resolve_chrome
    roots = tuple((trusted_roots or _trusted_chrome_roots)())
    try:
        resolution = resolve()
        executable = _safe_chrome_executable(resolution.executable, roots)
        if executable is None:
            raise FileNotFoundError
    except (FileNotFoundError, OSError, ValueError):
        return BrowserOpenResult(BrowserOpenOutcome.CHROME_UNAVAILABLE, error_code="chrome_unavailable")
    snapshot = process_snapshot or chrome_process_ids
    try:
        before = snapshot()
    except (OSError, RuntimeError):
        before = set()
    try:
        (launcher or _launch_chrome)(executable, validate_publish_to_web_src(exact_source))
    except ValueError:
        return BrowserOpenResult(BrowserOpenOutcome.INVALID_LINK, error_code="invalid_link")
    except (OSError, subprocess.SubprocessError):
        return BrowserOpenResult(BrowserOpenOutcome.LAUNCH_FAILED, error_code="launch_failed")
    try:
        after = snapshot()
    except (OSError, RuntimeError):
        after = set()
    return BrowserOpenResult(BrowserOpenOutcome.OPENED, launch_requested=True,
        process_detected=bool(after), process_preexisting=bool(before))
