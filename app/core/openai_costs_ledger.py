"""Ledger de saldo OpenAI baseado na Organization Costs API oficial.

Substitui o scraping via Puppeteer como caminho operacional padrão: nenhuma
janela de navegador é aberta, nenhuma aba é necessária, nenhuma automação
contra platform.openai.com é executada. O saldo exibido é calculado como

    calculated_balance_usd = baseline_balance_usd - custos_oficiais_desde(baseline_at)

onde os custos vêm exclusivamente de ``GET /v1/organization/costs`` (nunca de
usage, monthly limit, September spend visual ou credit grants).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from app.core.config import PROJECT_ROOT, get_setting


COSTS_API_URL = "https://api.openai.com/v1/organization/costs"
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "system" / "openai-balance-ledger.json"
CENTS = Decimal("0.01")


class CostsApiError(RuntimeError):
    """Erro de coleta com um código estável para a UI decidir o estado a exibir."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class BalanceLedgerRecord:
    """Estado mínimo e explícito do ledger de saldo."""

    baseline_balance_usd: Decimal | None = None
    baseline_at: datetime | None = None
    last_cost_sync_at: datetime | None = None
    calculated_balance_usd: Decimal | None = None
    source: str | None = None
    stale: bool = False
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "baseline_balance_usd": (
                str(self.baseline_balance_usd) if self.baseline_balance_usd is not None else None
            ),
            "baseline_at": self.baseline_at.isoformat() if self.baseline_at else None,
            "last_cost_sync_at": (
                self.last_cost_sync_at.isoformat() if self.last_cost_sync_at else None
            ),
            "calculated_balance_usd": (
                str(self.calculated_balance_usd) if self.calculated_balance_usd is not None else None
            ),
            "source": self.source,
            "stale": self.stale,
            "error": self.error,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BalanceLedgerRecord":
        return cls(
            baseline_balance_usd=_parse_decimal(payload.get("baseline_balance_usd")),
            baseline_at=_parse_datetime(payload.get("baseline_at")),
            last_cost_sync_at=_parse_datetime(payload.get("last_cost_sync_at")),
            calculated_balance_usd=_parse_decimal(payload.get("calculated_balance_usd")),
            source=payload.get("source") if isinstance(payload.get("source"), str) else None,
            stale=bool(payload.get("stale")),
            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
        )


class BalanceLedgerStore:
    """Persistência local mínima (JSON com escrita atômica). Sem PostgreSQL.

    Se o arquivo ainda não existir, a baseline operacional é semeada a partir
    de ``OPENAI_CREDIT_BASE_USD``/``OPENAI_CREDIT_BASE_AT`` — nunca de uma
    constante no código.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_LEDGER_PATH

    def load(self) -> BalanceLedgerRecord:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._seed_from_environment()
        if not isinstance(payload, dict):
            return self._seed_from_environment()
        return BalanceLedgerRecord.from_json(payload)

    @staticmethod
    def _seed_from_environment() -> BalanceLedgerRecord:
        baseline = _parse_decimal(get_setting("OPENAI_CREDIT_BASE_USD"))
        baseline_at = _parse_datetime(get_setting("OPENAI_CREDIT_BASE_AT"))
        if baseline is None or baseline_at is None:
            return BalanceLedgerRecord()
        return BalanceLedgerRecord(baseline_balance_usd=baseline, baseline_at=baseline_at)

    def save(self, record: BalanceLedgerRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(
                json.dumps(record.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


async def fetch_total_costs_since(admin_key: str, since: datetime, *, timeout: float = 30.0) -> Decimal:
    """Soma em Decimal todos os custos oficiais da Costs API desde `since`.

    Usa exclusivamente ``GET /v1/organization/costs`` (nunca usage, monthly
    limit ou credit grants) e pagina via ``has_more``/``next_page`` até
    esgotar os buckets.
    """

    total = Decimal("0")
    next_page: str | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            params: dict[str, Any] = {
                "start_time": int(since.timestamp()),
                "bucket_width": "1d",
                "limit": 180,
            }
            if next_page:
                params["next_page"] = next_page
            try:
                response = await client.get(
                    COSTS_API_URL,
                    headers={"Authorization": f"Bearer {admin_key}"},
                    params=params,
                )
            except httpx.HTTPError as error:
                raise CostsApiError("COSTS_API_UNAVAILABLE") from error
            if response.status_code in (401, 403):
                raise CostsApiError("COSTS_API_UNAUTHORIZED")
            if response.is_error:
                raise CostsApiError("COSTS_API_ERROR")
            try:
                payload = response.json()
            except ValueError as error:
                raise CostsApiError("COSTS_API_INVALID_RESPONSE") from error
            if not isinstance(payload, dict):
                raise CostsApiError("COSTS_API_INVALID_RESPONSE")

            for bucket in payload.get("data") or []:
                if not isinstance(bucket, dict):
                    continue
                for result in bucket.get("results") or []:
                    if not isinstance(result, dict):
                        continue
                    amount = result.get("amount")
                    value = amount.get("value") if isinstance(amount, dict) else None
                    parsed = _parse_decimal(value)
                    if parsed is not None:
                        total += parsed

            if not payload.get("has_more"):
                break
            next_page = payload.get("next_page")
            if not next_page:
                break
    return total


CostsFetcher = Callable[[str, datetime], Awaitable[Decimal]]
AdminKeyGetter = Callable[[], "str | None"]


class OpenAICostsLedgerService:
    """Fonte única do saldo exibido em SERVER ONLINE. Nunca abre navegador."""

    def __init__(
        self,
        *,
        store: BalanceLedgerStore | None = None,
        admin_key_getter: AdminKeyGetter | None = None,
        costs_fetcher: CostsFetcher | None = None,
        refresh_ms: int = 300000,
    ) -> None:
        self.store = store or BalanceLedgerStore()
        self.admin_key_getter = admin_key_getter or (lambda: get_setting("OPENAI_ADMIN_KEY"))
        self.costs_fetcher = costs_fetcher or fetch_total_costs_since
        self.refresh_ms = refresh_ms if refresh_ms > 0 else 300000
        self._lock = asyncio.Lock()
        self._record = self.store.load()
        self._next_refresh_at = 0.0

    async def current(self) -> dict[str, Any]:
        if asyncio.get_running_loop().time() >= self._next_refresh_at:
            return await self.refresh()
        return self._payload()

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        if not force and loop.time() < self._next_refresh_at:
            return self._payload()
        async with self._lock:
            if not force and loop.time() < self._next_refresh_at:
                return self._payload()
            self._record = await self._recompute(self._record)
            self.store.save(self._record)
            self._next_refresh_at = loop.time() + self.refresh_ms / 1000
            return self._payload()

    async def _recompute(self, record: BalanceLedgerRecord) -> BalanceLedgerRecord:
        if record.baseline_balance_usd is None or record.baseline_at is None:
            return replace(record, error="BALANCE_BASELINE_REQUIRED", stale=False)

        admin_key = self.admin_key_getter()
        if not admin_key:
            return replace(
                record,
                error="BALANCE_ADMIN_KEY_REQUIRED",
                stale=record.calculated_balance_usd is not None,
            )

        try:
            total_cost = await self.costs_fetcher(admin_key, record.baseline_at)
        except CostsApiError as error:
            return replace(record, error=error.code, stale=record.calculated_balance_usd is not None)
        except Exception:
            return replace(record, error="COSTS_API_ERROR", stale=record.calculated_balance_usd is not None)

        calculated = (record.baseline_balance_usd - total_cost).quantize(CENTS, rounding=ROUND_HALF_UP)
        if calculated == 0:
            calculated = Decimal("0.00")  # normaliza -0.00 vindo de arredondamento
        return replace(
            record,
            calculated_balance_usd=calculated,
            last_cost_sync_at=datetime.now(timezone.utc),
            source="official_costs_ledger",
            stale=False,
            error=None,
        )

    def _payload(self) -> dict[str, Any]:
        record = self._record
        balance = record.calculated_balance_usd
        baseline = record.baseline_balance_usd
        updated_at = record.last_cost_sync_at.isoformat() if record.last_cost_sync_at else None
        available = balance is not None
        return {
            "available": available,
            "ok": available and record.error is None,
            "balance_usd": float(balance) if balance is not None else None,
            "balance": float(balance) if balance is not None else None,
            "currency": "USD",
            "baseline_balance_usd": float(baseline) if baseline is not None else None,
            "baseline_at": record.baseline_at.isoformat() if record.baseline_at else None,
            "last_updated_at": updated_at,
            "updated_at": updated_at,
            "updatedAt": updated_at,
            "source": record.source or "official_costs_ledger",
            "stale": bool(record.stale),
            "authRequired": False,
            "error": record.error,
            "code": record.error,
            "refreshMs": self.refresh_ms,
        }
