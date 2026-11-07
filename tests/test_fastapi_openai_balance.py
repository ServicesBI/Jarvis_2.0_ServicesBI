import asyncio
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.openai_balance import OpenAIBalanceService
from app.core.openai_costs_ledger import OpenAICostsLedgerService
from app.main import create_app


class SequenceCollector:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class OpenAIBalanceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_ingest_updates_and_replaces_existing_cache(self):
        service = OpenAIBalanceService()
        first = await service.ingest(4.08, observed_at="2026-09-03T10:00:00Z")
        second = await service.ingest(3.97, observed_at="2026-09-03T10:05:00Z")
        self.assertEqual(first["source"], "chrome_bridge")
        self.assertEqual(second["balance_usd"], 3.97)
        self.assertTrue(second["available"])
        self.assertFalse(second["stale"])

    async def test_bridge_balance_becomes_stale_after_freshness_window(self):
        service = OpenAIBalanceService(refresh_ms=1)
        await service.ingest(4.08, observed_at="2026-09-03T10:00:00Z")
        await asyncio.sleep(0.01)
        state = await service.current()
        self.assertTrue(state["available"])
        self.assertTrue(state["stale"])

    async def test_valid_balance_is_cached_without_recollecting(self):
        collector = SequenceCollector({"balance": 17.42, "source": "openai_platform_home"})
        service = OpenAIBalanceService(collector=collector, refresh_ms=300000)
        first = await service.refresh()
        second = await service.current()
        self.assertEqual(first["balance_usd"], 17.42)
        self.assertEqual(second["balance_usd"], 17.42)
        self.assertEqual(collector.calls, 1)

    async def test_failed_refresh_preserves_last_balance_as_stale(self):
        collector = SequenceCollector(
            {"balance": 8.75, "source": "openai_platform_home"},
            RuntimeError("Authorization: secret-token"),
        )
        service = OpenAIBalanceService(collector=collector, refresh_ms=300000)
        confirmed = await service.refresh()
        failed = await service.refresh(force=True)
        self.assertEqual(failed["balance_usd"], confirmed["balance_usd"])
        self.assertTrue(failed["stale"])
        self.assertEqual(failed["updated_at"], confirmed["updated_at"])
        self.assertNotIn("secret-token", str(failed))

    async def test_no_cache_and_failure_is_structured_unavailable(self):
        service = OpenAIBalanceService(collector=SequenceCollector(RuntimeError("cookie=secret")))
        state = await service.refresh()
        self.assertFalse(state["available"])
        self.assertIsNone(state["balance_usd"])
        self.assertEqual(state["code"], "BALANCE_COLLECTION_FAILED")
        self.assertNotIn("secret", str(state))


class OpenAIBalanceRouteTests(unittest.TestCase):
    def test_bridge_heartbeat_is_exposed_without_sensitive_payload(self):
        service = OpenAIBalanceService()
        with TestClient(create_app(openai_balance_service=service)) as client:
            heartbeat = client.post(
                "/api/openai-balance/heartbeat",
                headers={"Origin": "chrome-extension://aacaopfflcfcocgpnklfggpmkjacbilc"},
                json={"stage": "content_script_loaded", "page_url": "https://platform.openai.com/home"},
            )
            status = client.get("/api/openai-balance/bridge-status")
        self.assertEqual(heartbeat.status_code, 202)
        self.assertTrue(status.json()["extension_seen"])
        self.assertTrue(status.json()["content_script_seen"])
        self.assertEqual(status.json()["extension_id"], "aacaopfflcfcocgpnklfggpmkjacbilc")
        self.assertNotIn("token", str(status.json()).lower())

    def test_authorized_bridge_origin_ingests_valid_balance_but_does_not_feed_the_normal_get_route(self):
        # A extensao Chrome bridge permanece dormente: aceitar um ingest ainda
        # funciona (compat), mas GET /api/openai-balance nao deve mais refletir
        # esse valor -- a fonte operacional padrao agora e o ledger de custos.
        service = OpenAIBalanceService()
        app = create_app(
            openai_balance_service=service,
            openai_costs_ledger_service=OpenAICostsLedgerService(store=_empty_ledger_store()),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/openai-balance/ingest",
                headers={"Origin": "chrome-extension://aacaopfflcfcocgpnklfggpmkjacbilc"},
                json={"balance_usd": 4.08, "currency": "USD", "observed_at": "2026-09-03T10:00:00Z", "source": "openai_platform_home"},
            )
            state = client.get("/api/openai-balance").json()
            bridge = client.get("/api/openai-balance/bridge-status").json()
        self.assertEqual(response.status_code, 202)
        self.assertNotEqual(state.get("source"), "chrome_bridge")
        self.assertNotEqual(state.get("balance_usd"), 4.08)
        self.assertTrue(bridge["ingest_received"])
        self.assertTrue(bridge["ingest_accepted"])
        self.assertTrue(bridge["credit_balance_found"])
        self.assertTrue(bridge["content_script_seen"])
        self.assertEqual(bridge["extension_id"], "aacaopfflcfcocgpnklfggpmkjacbilc")

    def test_bridge_rejects_wrong_origin_and_invalid_values(self):
        app = create_app(openai_balance_service=OpenAIBalanceService())
        with TestClient(app) as client:
            wrong_origin = client.post("/api/openai-balance/ingest", headers={"Origin": "https://evil.example"}, json={"balance_usd": 4.08, "currency": "USD", "observed_at": "2026-09-03T10:00:00Z", "source": "openai_platform_home"})
            invalid = client.post("/api/openai-balance/ingest", headers={"Origin": "chrome-extension://aacaopfflcfcocgpnklfggpmkjacbilc"}, json={"balance_usd": "4.08", "currency": "USD", "observed_at": "2026-09-03T10:00:00Z", "source": "openai_platform_home"})
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(invalid.status_code, 422)

    def test_route_exposes_costs_ledger_value_with_http_200(self):
        async def fake_costs_fetcher(admin_key, since):
            return Decimal("0.12")

        ledger_service = OpenAICostsLedgerService(
            store=_seeded_ledger_store(baseline="12.46", baseline_at="2026-09-01T00:00:00+00:00"),
            admin_key_getter=lambda: "sk-admin-test",
            costs_fetcher=fake_costs_fetcher,
        )
        with TestClient(create_app(openai_costs_ledger_service=ledger_service)) as client:
            response = client.get("/api/openai-balance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance_usd"], 12.34)
        self.assertEqual(response.json()["balance"], 12.34)
        self.assertEqual(response.json()["source"], "official_costs_ledger")

    def test_unavailable_metric_is_http_200_not_repeated_503(self):
        ledger_service = OpenAICostsLedgerService(store=_empty_ledger_store())
        with TestClient(create_app(openai_costs_ledger_service=ledger_service)) as client:
            response = client.get("/api/openai-balance")
            health = client.get("/api/providers/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertEqual(health.status_code, 200)

    def test_default_app_no_longer_wires_the_puppeteer_collector_and_wires_the_costs_ledger(self):
        application = create_app()
        legacy_service = application.state.openai_balance_service
        ledger_service = application.state.openai_costs_ledger_service
        self.assertIsNone(legacy_service.collector)
        self.assertIsInstance(ledger_service, OpenAICostsLedgerService)


def _empty_ledger_store() -> "BalanceLedgerStore":
    from app.core.openai_costs_ledger import BalanceLedgerRecord, BalanceLedgerStore

    class _MemoryStore(BalanceLedgerStore):
        def __init__(self) -> None:
            self._record = BalanceLedgerRecord()

        def load(self):
            return self._record

        def save(self, record):
            self._record = record

    return _MemoryStore()


def _seeded_ledger_store(*, baseline: str, baseline_at: str) -> "BalanceLedgerStore":
    from app.core.openai_costs_ledger import BalanceLedgerRecord, BalanceLedgerStore, _parse_datetime

    class _MemoryStore(BalanceLedgerStore):
        def __init__(self) -> None:
            self._record = BalanceLedgerRecord(
                baseline_balance_usd=Decimal(baseline),
                baseline_at=_parse_datetime(baseline_at),
            )

        def load(self):
            return self._record

        def save(self, record):
            self._record = record

    return _MemoryStore()


class OpenAIBalanceAuthRequiredTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_not_configured_reports_auth_required_not_fake_balance(self):
        service = OpenAIBalanceService(
            collector=SequenceCollector(_CodedError("BILLING_SESSION_NOT_CONFIGURED"))
        )
        state = await service.refresh()
        self.assertFalse(state["available"])
        self.assertIsNone(state["balance_usd"])
        self.assertTrue(state["authRequired"])
        self.assertEqual(state["code"], "BILLING_SESSION_NOT_CONFIGURED")

    async def test_expired_session_reports_auth_required_not_fake_balance(self):
        service = OpenAIBalanceService(
            collector=SequenceCollector(_CodedError("BILLING_AUTH_REQUIRED"))
        )
        state = await service.refresh()
        self.assertFalse(state["available"])
        self.assertIsNone(state["balance_usd"])
        self.assertTrue(state["authRequired"])
        self.assertEqual(state["code"], "BILLING_AUTH_REQUIRED")


class _CodedError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


if __name__ == "__main__":
    unittest.main()
