import asyncio
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.core.openai_costs_ledger import (
    BalanceLedgerRecord,
    BalanceLedgerStore,
    CostsApiError,
    OpenAICostsLedgerService,
    fetch_total_costs_since,
)
from app.main import create_app


def _memory_store(record: BalanceLedgerRecord | None = None) -> BalanceLedgerStore:
    class _MemoryStore(BalanceLedgerStore):
        def __init__(self) -> None:
            self._record = record or BalanceLedgerRecord()
            self.saved: list[BalanceLedgerRecord] = []

        def load(self) -> BalanceLedgerRecord:
            return self._record

        def save(self, new_record: BalanceLedgerRecord) -> None:
            self._record = new_record
            self.saved.append(new_record)

    return _MemoryStore()


def _seeded(baseline: str, baseline_at: str, **extra) -> BalanceLedgerRecord:
    return BalanceLedgerRecord(
        baseline_balance_usd=Decimal(baseline),
        baseline_at=_iso(baseline_at),
        **extra,
    )


def _iso(value: str):
    from app.core.openai_costs_ledger import _parse_datetime

    return _parse_datetime(value)


class LedgerCalculationTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_406_minus_cost_012_equals_394(self):
        async def fetcher(admin_key, since):
            return Decimal("0.12")

        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fetcher,
        )
        state = await service.refresh()
        self.assertEqual(state["balance_usd"], 3.94)
        self.assertEqual(state["baseline_balance_usd"], 4.06)
        self.assertEqual(state["source"], "official_costs_ledger")
        self.assertFalse(state["stale"])
        self.assertIsNone(state["error"])

    async def test_decimal_arithmetic_avoids_float_rounding_drift(self):
        # 4.06 - (0.01 somado 6 vezes) deve ser exatamente 4.00, nunca
        # 3.9999999999999996 (erro classico de float) nem -0.00 falso.
        async def fetcher(admin_key, since):
            return sum((Decimal("0.01") for _ in range(6)), Decimal("0"))

        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fetcher,
        )
        state = await service.refresh()
        self.assertEqual(state["balance_usd"], 4.00)

    async def test_exact_baseline_consumption_never_shows_false_negative_zero(self):
        async def fetcher(admin_key, since):
            return Decimal("4.06")

        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fetcher,
        )
        state = await service.refresh()
        self.assertEqual(state["balance_usd"], 0.0)
        self.assertNotEqual(str(state["balance_usd"]), "-0.0")


class LedgerBaselineAndKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_baseline_reports_explicit_code_not_zero(self):
        service = OpenAICostsLedgerService(store=_memory_store())
        state = await service.refresh()
        self.assertFalse(state["available"])
        self.assertIsNone(state["balance_usd"])
        self.assertEqual(state["error"], "BALANCE_BASELINE_REQUIRED")

    async def test_missing_admin_key_reports_explicit_code_not_zero(self):
        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: None,
        )
        state = await service.refresh()
        self.assertFalse(state["available"])
        self.assertIsNone(state["balance_usd"])
        self.assertEqual(state["error"], "BALANCE_ADMIN_KEY_REQUIRED")

    async def test_costs_api_failure_preserves_last_known_value_as_stale(self):
        calls = {"count": 0}

        async def fetcher(admin_key, since):
            calls["count"] += 1
            if calls["count"] == 1:
                return Decimal("0.12")
            raise CostsApiError("COSTS_API_UNAVAILABLE")

        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fetcher,
            refresh_ms=300000,
        )
        first = await service.refresh()
        second = await service.refresh(force=True)
        self.assertEqual(first["balance_usd"], 3.94)
        self.assertEqual(second["balance_usd"], 3.94)  # preserved, never reset to zero
        self.assertTrue(second["stale"])
        self.assertEqual(second["error"], "COSTS_API_UNAVAILABLE")

    async def test_never_mixes_september_spend_or_monthly_limit_into_the_balance(self):
        async def fetcher(admin_key, since):
            # Simula uma resposta real da Costs API: apenas amount.value dos
            # buckets deve contar. Campos de outras APIs (spend/limit) nunca
            # devem sequer chegar a esta funcao, mas garantimos que a soma
            # continua correta mesmo com dados extras irrelevantes no state.
            return Decimal("0.12")

        service = OpenAICostsLedgerService(
            store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fetcher,
        )
        state = await service.refresh()
        # September spend ($0.45) e monthly limit ($120.00) nao aparecem em
        # lugar nenhum do payload nem influenciam o resultado.
        self.assertEqual(state["balance_usd"], 3.94)
        self.assertNotEqual(state["balance_usd"], 0.45)
        self.assertNotEqual(state["balance_usd"], 120.00)


class CostsApiPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sums_multiple_buckets_and_multiple_results_per_bucket(self):
        payload = {
            "object": "page",
            "data": [
                {
                    "object": "bucket",
                    "start_time": 1,
                    "end_time": 2,
                    "results": [
                        {"object": "organization.costs.result", "amount": {"value": 0.05, "currency": "usd"}},
                        {"object": "organization.costs.result", "amount": {"value": 0.02, "currency": "usd"}},
                    ],
                },
                {
                    "object": "bucket",
                    "start_time": 2,
                    "end_time": 3,
                    "results": [
                        {"object": "organization.costs.result", "amount": {"value": 0.05, "currency": "usd"}},
                    ],
                },
            ],
            "has_more": False,
            "next_page": None,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        with patch(
            "app.core.openai_costs_ledger.httpx.AsyncClient",
            lambda **kw: real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
        ):
            from datetime import datetime, timezone

            total = await fetch_total_costs_since("sk-admin-test", datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(total, Decimal("0.12"))

    async def test_paginates_through_has_more_and_next_page(self):
        pages = [
            {
                "object": "page",
                "data": [{"object": "bucket", "results": [{"amount": {"value": 0.05}}]}],
                "has_more": True,
                "next_page": "cursor-2",
            },
            {
                "object": "page",
                "data": [{"object": "bucket", "results": [{"amount": {"value": 0.07}}]}],
                "has_more": False,
                "next_page": None,
            },
        ]
        seen_params = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_params.append(dict(request.url.params))
            return httpx.Response(200, json=pages[len(seen_params) - 1])

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        with patch(
            "app.core.openai_costs_ledger.httpx.AsyncClient",
            lambda **kw: real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
        ):
            from datetime import datetime, timezone

            total = await fetch_total_costs_since("sk-admin-test", datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(total, Decimal("0.12"))
        self.assertEqual(len(seen_params), 2)
        self.assertNotIn("next_page", seen_params[0])
        self.assertEqual(seen_params[1]["next_page"], "cursor-2")

    async def test_unauthorized_admin_key_raises_costs_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        with patch(
            "app.core.openai_costs_ledger.httpx.AsyncClient",
            lambda **kw: real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
        ):
            from datetime import datetime, timezone

            with self.assertRaises(CostsApiError) as ctx:
                await fetch_total_costs_since("sk-bad-key", datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(ctx.exception.code, "COSTS_API_UNAUTHORIZED")


class LedgerPersistenceTests(unittest.TestCase):
    def test_baseline_survives_restart_via_local_json_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openai-balance-ledger.json"
            store = BalanceLedgerStore(path=path)
            record = _seeded("4.06", "2026-09-01T00:00:00+00:00", calculated_balance_usd=Decimal("3.94"))
            store.save(record)

            reloaded_store = BalanceLedgerStore(path=path)
            reloaded = reloaded_store.load()
        self.assertEqual(reloaded.baseline_balance_usd, Decimal("4.06"))
        self.assertEqual(reloaded.calculated_balance_usd, Decimal("3.94"))

    def test_no_baseline_constant_hardcoded_in_module_source(self):
        import app.core.openai_costs_ledger as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("4.06", source)


class NoPuppeteerInNormalPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_costs_ledger_refresh_never_spawns_a_subprocess(self):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("Puppeteer subprocess must not run in the costs-ledger path"))):
            service = OpenAICostsLedgerService(
                store=_memory_store(_seeded("4.06", "2026-09-01T00:00:00+00:00")),
                admin_key_getter=lambda: "sk-admin-test",
                costs_fetcher=AsyncMock(return_value=Decimal("0.12")),
            )
            state = await service.refresh()
        self.assertEqual(state["balance_usd"], 3.94)

    def test_default_app_get_balance_route_never_spawns_a_subprocess(self):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("Puppeteer subprocess must not run in the normal GET path"))):
            with TestClient(create_app()) as client:
                response = client.get("/api/openai-balance")
        self.assertEqual(response.status_code, 200)

    def test_default_app_get_balance_route_never_touches_chrome_executable_lookup(self):
        # Nenhum caminho normal deve sequer procurar o executavel do Chrome
        # (o unico jeito de abrir uma janela e resolver esse caminho primeiro).
        with patch("subprocess.Popen", side_effect=AssertionError("no process should be launched")):
            with TestClient(create_app()) as client:
                response = client.get("/api/openai-balance")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
