"""Políticas centrais de autorização, paths e persistência de ações."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from app.actions.models import ActionRequest, ActionResult, PersistencePolicy


class ConfirmationRequiredError(PermissionError):
    """A ação é conhecida, mas exige confirmação explícita do usuário."""


class PathAccess(str, Enum):
    READ = "read"
    WRITE = "write"


class PathPolicy:
    def __init__(
        self,
        *,
        read_roots: tuple[Path, ...] = (),
        write_roots: tuple[Path, ...] = (),
    ) -> None:
        self.read_roots = tuple(root.resolve() for root in read_roots)
        self.write_roots = tuple(root.resolve() for root in write_roots)

    def validate(self, raw_path: str | Path, *, access: PathAccess) -> Path:
        path = Path(raw_path).expanduser().resolve()
        roots = self.read_roots if access is PathAccess.READ else self.write_roots
        if not any(path == root or root in path.parents for root in roots):
            raise PermissionError("Caminho fora das áreas autorizadas para a ação.")
        if access is PathAccess.READ and not path.exists():
            raise FileNotFoundError("Caminho de leitura não encontrado.")
        return path


class ActionPolicy:
    _sensitive_markers = (
        "token",
        "secret",
        "credential",
        "password",
        "api_key",
        "clipboard",
        "prompt",
    )

    def authorize(self, definition: Any, request: ActionRequest) -> None:
        if definition.confirmation_required and not request.confirmed:
            raise ConfirmationRequiredError(
                f"A ação {definition.name} exige confirmação explícita."
            )

    def persistent_result(
        self,
        result: ActionResult,
        persistence: PersistencePolicy,
    ) -> dict[str, Any]:
        payload = result.model_dump(mode="json")
        if persistence is PersistencePolicy.MINIMAL:
            payload["data"] = {}
            return payload
        return self._sanitize(payload)

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).casefold()
                if any(marker in normalized for marker in self._sensitive_markers):
                    sanitized[str(key)] = "[REDACTED]"
                else:
                    sanitized[str(key)] = self._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value
