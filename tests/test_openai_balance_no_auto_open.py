"""Regressao do bug real: platform.openai.com abrindo sozinha no Chrome do
usuario. A causa raiz era a extensao integrations/chrome/openai-balance-bridge
(onInstalled/onStartup/alarme de 5 min chamando chrome.tabs.create) -- um
componente que roda dentro do navegador, fora do processo Python/Node, e por
isso invisivel para testes que so exercitam o backend. Este arquivo cobre os
dois lados: (1) estaticamente, que o codigo-fonte da extensao nao contem mais
nenhum caminho capaz de criar/abrir uma aba sozinha; (2) dinamicamente, que
nenhum fluxo normal do backend (create_app, GET /api/openai-balance, refresh
do ledger, troca de executor AUTO/CLAUDE/CODEX) chama webbrowser/subprocess/
Chrome ou faz qualquer request HTTP para platform.openai.com.
"""

import asyncio
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT
from app.core.openai_costs_ledger import BalanceLedgerRecord, BalanceLedgerStore, OpenAICostsLedgerService
from app.main import create_app


BRIDGE_DIR = PROJECT_ROOT / "integrations" / "chrome" / "openai-balance-bridge"


def _memory_store(record: BalanceLedgerRecord | None = None) -> BalanceLedgerStore:
    class _MemoryStore(BalanceLedgerStore):
        def __init__(self) -> None:
            self._record = record or BalanceLedgerRecord(
                baseline_balance_usd=Decimal("4.06"),
                baseline_at=None,
            )

        def load(self):
            return self._record

        def save(self, new_record):
            self._record = new_record

    from app.core.openai_costs_ledger import _parse_datetime

    store = _MemoryStore()
    if store._record.baseline_at is None:
        store._record = BalanceLedgerRecord(
            baseline_balance_usd=Decimal("4.06"),
            baseline_at=_parse_datetime("2026-09-05T10:49:00-03:00"),
        )
    return store


class ChromeExtensionStaticRegressionTests(unittest.TestCase):
    """A extensao ja instalada no Chrome real do usuario roda fora do nosso
    processo: o unico jeito de garantir que ela nunca mais abre uma aba
    sozinha e travar isso no proprio codigo-fonte que ela carrega."""

    def setUp(self) -> None:
        self.background_js = (BRIDGE_DIR / "background.js").read_text(encoding="utf-8")
        self.manifest_json = (BRIDGE_DIR / "manifest.json").read_text(encoding="utf-8")

    def test_background_never_creates_or_queries_tabs(self):
        self.assertNotIn("chrome.tabs.create", self.background_js)
        self.assertNotIn("chrome.tabs.query", self.background_js)
        self.assertNotIn("ensureHomeTab", self.background_js)

    def test_background_has_no_alarm_driven_reopen(self):
        self.assertNotIn("chrome.alarms", self.background_js)
        self.assertNotIn("onAlarm", self.background_js)

    def test_background_has_no_startup_or_install_side_effects(self):
        self.assertNotIn("onInstalled", self.background_js)
        self.assertNotIn("onStartup", self.background_js)

    def test_manifest_no_longer_requests_tabs_or_alarms_permission(self):
        self.assertNotIn('"tabs"', self.manifest_json)
        self.assertNotIn('"alarms"', self.manifest_json)

    def test_background_only_reacts_to_messages_never_initiates_navigation(self):
        # O unico ponto de entrada aceitavel e um listener passivo de mensagens
        # vindas de um content script ja rodando numa aba aberta pelo usuario.
        self.assertIn("chrome.runtime.onMessage.addListener", self.background_js)
        for forbidden in ("window.open", "location.href", "location.assign", "location.replace", "chrome.windows.create"):
            self.assertNotIn(forbidden, self.background_js)


class NoAutoOpenInBackendPathTests(unittest.IsolatedAsyncioTestCase):
    async def _assert_no_browser_or_subprocess(self, coro_factory):
        with (
            patch("webbrowser.open", side_effect=AssertionError("webbrowser.open must never run")) as wb_open,
            patch("webbrowser.open_new", side_effect=AssertionError("webbrowser.open_new must never run")),
            patch("webbrowser.open_new_tab", side_effect=AssertionError("webbrowser.open_new_tab must never run")),
            patch("os.startfile", side_effect=AssertionError("os.startfile must never run"), create=True),
            patch("subprocess.Popen", side_effect=AssertionError("subprocess.Popen must never run")),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("no subprocess (Puppeteer/Node) may run"))),
        ):
            await coro_factory()
        self.assertFalse(wb_open.called)

    async def test_costs_ledger_refresh_never_opens_a_browser(self):
        async def run():
            service = OpenAICostsLedgerService(
                store=_memory_store(),
                admin_key_getter=lambda: "sk-admin-test",
                costs_fetcher=AsyncMock(return_value=Decimal("0.00")),
            )
            state = await service.refresh(force=True)
            self.assertEqual(state["balance_usd"], 4.06)

        await self._assert_no_browser_or_subprocess(run)

    async def test_get_balance_route_never_opens_a_browser(self):
        async def run():
            ledger_service = OpenAICostsLedgerService(
                store=_memory_store(),
                admin_key_getter=lambda: "sk-admin-test",
                costs_fetcher=AsyncMock(return_value=Decimal("0.00")),
            )
            with TestClient(create_app(openai_costs_ledger_service=ledger_service)) as client:
                response = client.get("/api/openai-balance")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["balance_usd"], 4.06)

        await self._assert_no_browser_or_subprocess(run)

    async def test_executor_mode_switch_auto_claude_codex_never_opens_a_browser(self):
        async def run():
            with TestClient(create_app()) as client:
                for mode in ("auto", "claude", "codex", "auto"):
                    response = client.post("/api/executor/mode", json={"mode": mode})
                    self.assertEqual(response.status_code, 200)
                    balance = client.get("/api/openai-balance")
                    self.assertEqual(balance.status_code, 200)

        await self._assert_no_browser_or_subprocess(run)

    async def test_default_app_startup_never_opens_a_browser(self):
        async def run():
            with TestClient(create_app()) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)

        await self._assert_no_browser_or_subprocess(run)


class NoRequestToPlatformOpenaiComTests(unittest.IsolatedAsyncioTestCase):
    """Nenhuma requisicao HTTP de saida do backend pode ter platform.openai.com
    como host -- so api.openai.com (Costs API) e permitido."""

    async def test_costs_fetcher_only_ever_targets_the_costs_api_host(self):
        from app.core.openai_costs_ledger import fetch_total_costs_since
        import httpx

        requested_hosts = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_hosts.append(request.url.host)
            return httpx.Response(200, json={"object": "page", "data": [], "has_more": False})

        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient
        from datetime import datetime, timezone

        with patch(
            "app.core.openai_costs_ledger.httpx.AsyncClient",
            lambda **kw: real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
        ):
            await fetch_total_costs_since("sk-admin-test", datetime(2026, 9, 5, tzinfo=timezone.utc))

        self.assertTrue(requested_hosts)
        for host in requested_hosts:
            self.assertEqual(host, "api.openai.com")
            self.assertNotEqual(host, "platform.openai.com")


if __name__ == "__main__":
    unittest.main()
