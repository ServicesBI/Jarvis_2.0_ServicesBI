"""Fase 4B: painel AIOX-CORE deve acompanhar o status runtime real via polling.

Segue a mesma convenção de tests/test_fastapi_agent_frontend.py (Fase 3B):
asserções estruturais sobre o texto de public/script.js, já que o arquivo
manipula `document` diretamente e não roda isolado sob node:test (sem jsdom).
"""

from __future__ import annotations

import re
import unittest

from app.core.config import PROJECT_ROOT


class AioxAgentPollingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frontend = (PROJECT_ROOT / "public" / "script.js").read_text(
            encoding="utf-8"
        )

    def _aiox_block(self) -> str:
        marker = "AIOX AGENTS"
        self.assertIn(marker, self.frontend)
        return self.frontend.split(marker, 1)[1]

    # CASO 1 (carga inicial) permanece coberto por
    # test_fastapi_agent_frontend.py::test_frontend_consumes_and_validates_the_agents_api_payload

    def test_panel_polls_agents_status_periodically(self) -> None:
        """CASO 2/3/4: o painel deve buscar /api/agents em loop, nao so uma vez."""
        block = self._aiox_block()
        interval_calls = re.findall(
            r"setInterval\(\s*loadAioxAgents\s*,\s*(\w+)\s*\)", block
        )
        self.assertEqual(
            len(interval_calls),
            1,
            "deve existir exatamente um setInterval(loadAioxAgents, ...)",
        )
        interval_arg = interval_calls[0]
        if interval_arg.isdigit():
            interval_ms = int(interval_arg)
        else:
            constant_match = re.search(
                rf"const\s+{re.escape(interval_arg)}\s*=\s*(\d+)", block
            )
            self.assertIsNotNone(
                constant_match, f"constante {interval_arg} nao encontrada"
            )
            interval_ms = int(constant_match.group(1))
        self.assertGreaterEqual(interval_ms, 2000)
        self.assertLessEqual(interval_ms, 5000)

    def test_agents_fetch_is_not_duplicated_by_polling(self) -> None:
        """CASO 10: polling reaproveita loadAioxAgents, sem 2º fetch concorrente."""
        self.assertEqual(self.frontend.count("fetch('/api/agents'"), 1)
        self.assertEqual(self.frontend.count("async function loadAioxAgents"), 1)

    def test_polling_reuses_the_existing_staleness_guard_primitive(self) -> None:
        """CASO 6: nenhuma segunda estrategia de anti-race deve ser inventada."""
        block = self._aiox_block()
        self.assertIn("ExecutorStatus.createStalenessGuard()", block)
        self.assertIn(".next()", block)
        self.assertIn(".isCurrent(", block)
        # nao pode reimplementar o guard com contador proprio incompativel,
        # nem trocar polling por um transporte novo dentro do bloco de agentes
        self.assertNotIn("new AbortController", block)
        self.assertNotIn("new WebSocket", block)
        self.assertNotIn("EventSource", block)

    def test_render_always_reflects_the_literal_payload_status(self) -> None:
        """CASO 5/9: nenhum card e tratado de forma especial, nenhum status fabricado."""
        block = self._aiox_block()
        self.assertIn("AgentStatusView.projectAgentStatus(agent.status)", block)
        self.assertNotIn("agent.id === 'neo'", block)
        self.assertNotIn('agent.id === "neo"', block)
        self.assertNotIn("'working'", block)
        self.assertNotIn('"working"', block)

    def test_transient_polling_failure_keeps_last_snapshot(self) -> None:
        """CASO 7: falha de polling nao apaga snapshot valido nem fabrica erro imediato."""
        block = self._aiox_block()
        catch_body = block.split("async function loadAioxAgents", 1)[1]
        self.assertIn("loadState", catch_body)
        self.assertIn("renderAgentLoadError", catch_body)
        # a chamada a renderAgentLoadError deve ser condicional (nao incondicional
        # a cada falha), provando que um snapshot valido pode ser preservado
        unconditional = re.search(
            r"catch[^{]*\{\s*renderAgentLoadError\(\);?\s*\}", catch_body
        )
        self.assertIsNone(
            unconditional,
            "renderAgentLoadError não pode ser chamado incondicionalmente a cada falha",
        )


if __name__ == "__main__":
    unittest.main()
