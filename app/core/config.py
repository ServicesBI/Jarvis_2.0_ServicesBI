"""Configuração mínima e segura da fundação FastAPI."""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "public"


def get_setting(name: str) -> str | None:
    """Lê uma configuração do ambiente ou do .env local sem efeitos colaterais."""

    environment_value = os.getenv(name)
    if environment_value is not None:
        return environment_value

    env_path = PROJECT_ROOT / ".env"
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("\"'")
    except (OSError, UnicodeError):
        return None
    return None


def _runtime_host() -> str:
    host = (get_setting("HOST") or "127.0.0.1").strip().lower()
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("HOST deve usar uma interface de loopback local.")
    return host


def _runtime_port() -> int:
    raw_port = (get_setting("PORT") or "8000").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT deve ser um inteiro entre 1 e 65535.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT deve ser um inteiro entre 1 e 65535.")
    return port


HOST = _runtime_host()
PORT = _runtime_port()

LOCAL_ORIGINS = (
    f"http://127.0.0.1:{PORT}",
    f"http://localhost:{PORT}",
)


def _workspace_root() -> Path:
    root = Path(
        get_setting("JARVIS_WORKSPACE_ROOT") or r"D:\Jarvis"
    ).expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("JARVIS_WORKSPACE_ROOT nao pode autorizar um volume inteiro.")
    return root


WORKSPACE_ROOT = _workspace_root()
WORD_WORKSPACE = WORKSPACE_ROOT / "Word"
EXCEL_WORKSPACE = WORKSPACE_ROOT / "Excel"
POWERBI_WORKSPACE = WORKSPACE_ROOT / "Power BI"
VSCODE_WORKSPACE = WORKSPACE_ROOT / "VS Code"
