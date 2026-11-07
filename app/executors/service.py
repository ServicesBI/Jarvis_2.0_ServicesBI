"""Estado em memória e descoberta dos executores suportados."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from threading import RLock

from app.core.config import get_setting
from app.executors.cli import CliDetection, detect_cli
from app.executors.model_registry import DEFAULT_MODEL_PROFILE, ModelRegistry


VALID_EXECUTOR_MODES = ("auto", "claude", "codex")
_CODEX_EXTENSION_PATTERN = "openai.chatgpt-*"
_CODEX_RELATIVE_EXECUTABLE = Path("bin") / "windows-x86_64" / "codex.exe"


def _bundled_codex_command(user_profile: Path) -> str | None:
    extensions = user_profile / ".vscode" / "extensions"
    try:
        candidates = sorted(
            extensions.glob(_CODEX_EXTENSION_PATTERN),
            key=lambda path: path.name.casefold(),
            reverse=True,
        )
    except OSError:
        return None
    for extension in candidates:
        executable = extension / _CODEX_RELATIVE_EXECUTABLE
        try:
            if extension.is_dir() and executable.is_file():
                return str(executable.resolve())
        except OSError:
            continue
    return None


def codex_subprocess_environment() -> dict[str, str]:
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        return {"CODEX_HOME": configured}
    user_profile = os.environ.get("USERPROFILE", "").strip()
    profile = Path(user_profile) if user_profile else Path.home()
    return {"CODEX_HOME": str(profile / ".codex")}


def _initial_mode() -> str:
    requested = (get_setting("JARVIS_EXECUTOR_MODE") or "").strip().lower()
    return requested if requested in VALID_EXECUTOR_MODES else "auto"


class ExecutorService:
    """Mantém seleção em memória sem depender da presença dos CLIs."""

    valid_modes = VALID_EXECUTOR_MODES

    def __init__(
        self,
        initial_mode: str = "auto",
        *,
        model_registry: ModelRegistry | None = None,
    ) -> None:
        self._lock = RLock()
        self._mode = initial_mode if initial_mode in self.valid_modes else "auto"
        self.model_registry = model_registry or ModelRegistry.default()
        self._profiles = {
            "codex": DEFAULT_MODEL_PROFILE.value,
            "claude": DEFAULT_MODEL_PROFILE.value,
        }

    def get_mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: object) -> str:
        requested = str(mode or "").strip().lower()
        if requested not in self.valid_modes:
            raise ValueError("Modo inválido")
        with self._lock:
            self._mode = requested
            return self._mode

    def get_profile(self, provider: str) -> str:
        with self._lock:
            try:
                return self._profiles[provider]
            except KeyError as error:
                raise ValueError(f"Executor desconhecido: {provider}") from error

    def set_profile(self, provider: str, profile: object) -> str:
        normalized = str(profile or "").strip().lower()
        self.model_registry.resolve(provider, normalized)
        with self._lock:
            if provider not in self._profiles:
                raise ValueError(f"Executor desconhecido: {provider}")
            self._profiles[provider] = normalized
        return normalized

    def resolve_model(self, provider: str):
        return self.model_registry.resolve(provider, self.get_profile(provider))

    @staticmethod
    def _native_claude_command(command: str) -> str:
        launcher = Path(command)
        if launcher.name.casefold() == "claude" and launcher.parent == Path("."):
            appdata = os.environ.get("APPDATA", "").strip()
            if appdata:
                launcher = Path(appdata) / "npm" / "claude.CMD"
        if launcher.suffix.casefold() not in {".cmd", ".bat"}:
            return command
        native = (
            launcher.parent
            / "node_modules"
            / "@anthropic-ai"
            / "claude-code"
            / "bin"
            / "claude.exe"
        )
        return str(native) if native.is_file() else command

    def get_command(self, provider: str) -> str:
        if provider == "claude":
            configured = (
                get_setting("CLAUDE_CLI_PATH")
                or get_setting("JARVIS_CLAUDE_CMD")
                or "claude"
            ).strip() or "claude"
            return self._native_claude_command(configured)
        if provider == "codex":
            configured = (get_setting("JARVIS_CODEX_CMD") or "").strip()
            if configured:
                return configured
            if shutil.which("codex") is not None:
                return "codex"
            user_profile = os.environ.get("USERPROFILE", "").strip()
            profile = Path(user_profile) if user_profile else Path.home()
            return _bundled_codex_command(profile) or "codex"
        raise ValueError(f"Executor desconhecido: {provider}")

    def detect_executors(self) -> dict[str, CliDetection]:
        """Detecta Claude e Codex passivamente, apenas quando solicitado."""

        claude_command = self.get_command("claude")
        codex_command = self.get_command("codex")
        return {
            "claude": detect_cli("Claude", claude_command),
            "codex": detect_cli("Codex", codex_command),
        }

executor_service = ExecutorService(initial_mode=_initial_mode())
