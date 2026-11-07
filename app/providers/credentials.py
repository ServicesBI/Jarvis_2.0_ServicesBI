"""Narrow secret-storage contract and subprocess bridge to Windows DPAPI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


MAX_SECRET_LENGTH = 64 * 1024
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_BRIDGE_PATH = (
    Path(__file__).resolve().parents[2]
    / "integrations"
    / "node"
    / "connections"
    / "credential-bridge.js"
)


class CredentialErrorCode(str, Enum):
    INVALID_REFERENCE = "invalid_reference"
    INVALID_SECRET = "invalid_secret"
    SECRET_NOT_FOUND = "secret_not_found"
    BRIDGE_UNAVAILABLE = "bridge_unavailable"
    BRIDGE_TIMEOUT = "bridge_timeout"
    INVALID_BRIDGE_RESPONSE = "invalid_bridge_response"
    DPAPI_FAILED = "dpapi_failed"


class CredentialStoreError(RuntimeError):
    """Credential failure with a stable code and no sensitive material."""

    def __init__(self, code: CredentialErrorCode, message: str) -> None:
        if not isinstance(code, CredentialErrorCode):
            raise TypeError("code must be CredentialErrorCode")
        super().__init__(message)
        self.code = code


@runtime_checkable
class SecretStore(Protocol):
    def set_secret(self, reference: str, secret: str) -> str: ...

    def get_secret(self, reference: str) -> str: ...

    def has_secret(self, reference: str) -> bool: ...

    def delete_secret(self, reference: str) -> bool: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]


class DpapiSecretStore:
    """Short-lived JSON subprocess adapter for the existing Node DPAPI vault."""

    def __init__(
        self,
        *,
        node_path: str = "node",
        bridge_path: Path = DEFAULT_BRIDGE_PATH,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        runner: Runner = subprocess.run,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._node_path = str(node_path)
        self._bridge_path = Path(bridge_path).resolve()
        self._timeout_seconds = float(timeout_seconds)
        self._runner = runner

    def set_secret(self, reference: str, secret: str) -> str:
        normalized = self._validate_reference(reference)
        self._validate_secret(secret)
        response = self._invoke(
            {"operation": "set", "reference": normalized, "secret": secret}
        )
        if response.get("reference") != normalized:
            raise self._invalid_response()
        return normalized

    def get_secret(self, reference: str) -> str:
        response = self._invoke(
            {"operation": "get", "reference": self._validate_reference(reference)}
        )
        secret = response.get("secret")
        if secret is None:
            raise CredentialStoreError(
                CredentialErrorCode.SECRET_NOT_FOUND,
                "Credential was not found.",
            )
        if not isinstance(secret, str):
            raise self._invalid_response()
        return secret

    def has_secret(self, reference: str) -> bool:
        response = self._invoke(
            {"operation": "has", "reference": self._validate_reference(reference)}
        )
        exists = response.get("exists")
        if not isinstance(exists, bool):
            raise self._invalid_response()
        return exists

    def delete_secret(self, reference: str) -> bool:
        response = self._invoke(
            {"operation": "delete", "reference": self._validate_reference(reference)}
        )
        deleted = response.get("deleted")
        if not isinstance(deleted, bool):
            raise self._invalid_response()
        return deleted

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        arguments = [self._node_path, str(self._bridge_path)]
        options: dict[str, Any] = {
            "input": json.dumps(request, ensure_ascii=False),
            "text": True,
            "encoding": "utf-8",
            "capture_output": True,
            "timeout": self._timeout_seconds,
            "shell": False,
            "cwd": str(self._bridge_path.parent),
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = self._runner(arguments, **options)
        except subprocess.TimeoutExpired:
            raise CredentialStoreError(
                CredentialErrorCode.BRIDGE_TIMEOUT,
                "Credential bridge timed out.",
            ) from None
        except (FileNotFoundError, OSError):
            raise CredentialStoreError(
                CredentialErrorCode.BRIDGE_UNAVAILABLE,
                "Credential bridge is unavailable.",
            ) from None

        try:
            response = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            raise self._invalid_response() from None
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise self._invalid_response()
        if completed.returncode != 0 or response["ok"] is not True:
            self._raise_bridge_error(response.get("error"))
        return response

    @staticmethod
    def _validate_reference(reference: str) -> str:
        if not isinstance(reference, str) or not REFERENCE_PATTERN.fullmatch(reference):
            raise CredentialStoreError(
                CredentialErrorCode.INVALID_REFERENCE,
                "Credential reference is invalid.",
            )
        return reference

    @staticmethod
    def _validate_secret(secret: str) -> None:
        if not isinstance(secret, str) or not secret or len(secret) > MAX_SECRET_LENGTH:
            raise CredentialStoreError(
                CredentialErrorCode.INVALID_SECRET,
                "Credential value is invalid.",
            )

    @staticmethod
    def _invalid_response() -> CredentialStoreError:
        return CredentialStoreError(
            CredentialErrorCode.INVALID_BRIDGE_RESPONSE,
            "Credential bridge returned an invalid response.",
        )

    @staticmethod
    def _raise_bridge_error(error_code: object) -> None:
        unavailable_codes = {
            "SECURE_VAULT_UNAVAILABLE",
            "LOCAL_APP_DATA_UNAVAILABLE",
            "DPAPI_HELPER_UNAVAILABLE",
        }
        if error_code in unavailable_codes:
            raise CredentialStoreError(
                CredentialErrorCode.BRIDGE_UNAVAILABLE,
                "Credential bridge is unavailable.",
            )
        raise CredentialStoreError(
            CredentialErrorCode.DPAPI_FAILED,
            "Credential protection operation failed.",
        )
