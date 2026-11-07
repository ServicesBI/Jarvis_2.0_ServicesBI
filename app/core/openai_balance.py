"""Coleta bounded e cache do saldo confirmado da OpenAI API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT


BalanceCollector = Callable[[], Awaitable[dict[str, Any]]]

KNOWN_BALANCE_ERROR_CODES = frozenset({
    "BILLING_SESSION_NOT_CONFIGURED",
    "BILLING_AUTH_REQUIRED",
    "BILLING_PAGE_UNAVAILABLE",
    "GOOGLE_CHROME_NOT_FOUND",
    "BALANCE_NOT_FOUND",
    "BALANCE_AMBIGUOUS",
})


class BalanceCollectionError(RuntimeError):
    """Erro de coleta com um código estável para a UI decidir o estado a exibir."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def collect_openai_balance() -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        "node",
        str(PROJECT_ROOT / "scripts" / "openai-balance-read.js"),
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=90)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise BalanceCollectionError("BALANCE_COLLECTION_TIMEOUT") from None
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BalanceCollectionError("BALANCE_INVALID_RESPONSE") from None
    if process.returncode != 0:
        error_code = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error_code, str) and error_code in KNOWN_BALANCE_ERROR_CODES:
            raise BalanceCollectionError(error_code)
        raise BalanceCollectionError("BALANCE_COLLECTION_FAILED")
    try:
        balance = payload["balance"]
    except (KeyError, TypeError):
        raise BalanceCollectionError("BALANCE_INVALID_RESPONSE") from None
    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or balance < 0:
        raise BalanceCollectionError("BALANCE_INVALID_RESPONSE")
    return {"balance": round(float(balance), 2), "source": "openai_platform_home"}


class OpenAIBalanceService:
    def __init__(self, *, collector: BalanceCollector | None = None, refresh_ms: int = 300000) -> None:
        self.collector = collector
        self.refresh_ms = refresh_ms if refresh_ms > 0 else 300000
        self._lock = asyncio.Lock()
        self._state = self._unavailable("BALANCE_NOT_COLLECTED")
        self._next_refresh_at = 0.0
        self._bridge = {"extension_seen": False, "extension_id": None, "last_heartbeat_at": None,
            "content_script_seen": False, "credit_balance_found": False,
            "last_balance_observed": None, "ingest_received": False, "ingest_accepted": False,
            "last_error_code": None, "last_error_stage": None, "updated_at": None}

    def _unavailable(self, code: str) -> dict[str, Any]:
        return {"available": False, "ok": False, "balance_usd": None, "balance": None,
                "currency": "USD", "updated_at": None, "updatedAt": None,
                "source": "openai_platform_home", "stale": False,
                "authRequired": code in {"BILLING_AUTH_REQUIRED", "BILLING_SESSION_NOT_CONFIGURED"},
                "code": code, "refreshMs": self.refresh_ms}

    async def current(self) -> dict[str, Any]:
        if asyncio.get_running_loop().time() >= self._next_refresh_at:
            if self.collector is not None:
                return await self.refresh()
            if self._state.get("available"):
                self._state = {**self._state, "stale": True}
        return dict(self._state)

    async def ingest(self, balance_usd: float, *, observed_at: str, extension_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            value = round(float(balance_usd), 2)
            self._state = {"available": True, "ok": True, "balance_usd": value, "balance": value,
                "currency": "USD", "updated_at": observed_at, "updatedAt": observed_at,
                "source": "chrome_bridge", "stale": False, "authRequired": False,
                "code": None, "refreshMs": self.refresh_ms}
            self._next_refresh_at = asyncio.get_running_loop().time() + self.refresh_ms / 1000
            self._bridge.update({"extension_seen": True, "extension_id": extension_id or self._bridge["extension_id"],
                "content_script_seen": True, "credit_balance_found": True,
                "last_balance_observed": value, "ingest_received": True, "ingest_accepted": True,
                "last_error_code": None, "last_error_stage": None, "updated_at": observed_at})
            return dict(self._state)

    async def heartbeat(self, *, extension_id: str, stage: str, observed_at: str) -> None:
        async with self._lock:
            self._bridge.update({"extension_seen": True, "extension_id": extension_id,
                "last_heartbeat_at": observed_at, "updated_at": observed_at})
            if stage == "content_script_loaded":
                self._bridge["content_script_seen"] = True
            elif stage == "credit_balance_found":
                self._bridge["credit_balance_found"] = True
            elif stage == "ingest_accepted":
                self._bridge["ingest_received"] = True
                self._bridge["ingest_accepted"] = True
            elif stage == "ingest_rejected":
                self._bridge.update({"ingest_received": True, "ingest_accepted": False,
                    "last_error_code": "INGEST_REJECTED", "last_error_stage": stage})

    def bridge_status(self) -> dict[str, Any]:
        return dict(self._bridge)

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        if not force and loop.time() < self._next_refresh_at:
            return dict(self._state)
        async with self._lock:
            if not force and loop.time() < self._next_refresh_at:
                return dict(self._state)
            try:
                if self.collector is None:
                    raise RuntimeError("BALANCE_BRIDGE_NOT_SYNCED")
                result = await self.collector()
                value = round(float(result["balance"]), 2)
                if value < 0:
                    raise ValueError
                updated = datetime.now(timezone.utc).isoformat()
                self._state = {"available": True, "ok": True, "balance_usd": value, "balance": value,
                    "currency": "USD", "updated_at": updated, "updatedAt": updated,
                    "source": str(result.get("source") or "openai_platform_home"), "stale": False,
                    "authRequired": False, "code": None, "refreshMs": self.refresh_ms}
            except Exception as error:
                code = getattr(error, "code", None)
                if not isinstance(code, str):
                    code = "BALANCE_COLLECTION_FAILED"
                if self._state.get("available"):
                    self._state = {
                        **self._state,
                        "stale": True,
                        "code": code,
                        "authRequired": code in {"BILLING_AUTH_REQUIRED", "BILLING_SESSION_NOT_CONFIGURED"},
                    }
                else:
                    self._state = self._unavailable(code)
            self._next_refresh_at = loop.time() + self.refresh_ms / 1000
            return dict(self._state)
