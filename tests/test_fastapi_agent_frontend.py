"""Contrato bounded entre GET /api/agents e o painel AIOX-Core."""

import re
import unittest

from app.core.config import PROJECT_ROOT
from app.agents.registry import CANONICAL_AGENT_DEFINITIONS


CANONICAL_NAMES = (
    "MORPHEUS",
    "ORACLE",
    "NIKITA",
    "ATHENA",
    "NEO",
    "HEPHAESTUS",
    "APOLLO",
    "TRINITY",
)
LEGACY_NAMES = (
    "ORION",
    "ARIA",
    "DEX",
    "DARA",
    "SAGE",
    "LUMA",
    "MORGAN",
    "PAX",
    "ATLAS",
    "QUINN",
    "RIVER",
    "CRAFT",
)


class AgentFrontendContractTests(unittest.TestCase):
    def setUp(self):
        self.index = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.frontend = (PROJECT_ROOT / "public" / "script.js").read_text(encoding="utf-8")
        self.panel = self.index.split('<div class="panel jarvas-aiox-panel">', 1)[1].split(
            '<div class="panel jarvas-ai-models-panel">', 1
        )[0]

    def test_panel_has_only_the_runtime_grid_without_hardcoded_catalog(self):
        self.assertIn('id="aiox-agents-grid"', self.panel)
        self.assertNotIn('class="aiox-card', self.panel)
        for name in (*CANONICAL_NAMES, *LEGACY_NAMES, "ZEUS"):
            with self.subTest(name=name):
                self.assertNotIn(name, self.panel)

    def test_frontend_consumes_and_validates_the_agents_api_payload(self):
        self.assertEqual(self.frontend.count("fetch('/api/agents'"), 1)
        for field in ("agent.id", "agent.name", "agent.role", "agent.status"):
            with self.subTest(field=field):
                self.assertIn(field, self.frontend)
        self.assertIn("payload.count !== payload.agents.length", self.frontend)
        self.assertIn("card.dataset.agentId", self.frontend)
        self.assertIn("card.dataset.agentStatus", self.frontend)

    def test_api_failure_is_neutral_and_does_not_create_a_fallback_catalog(self):
        self.assertIn("function renderAgentLoadError", self.frontend)
        self.assertIn("async function loadAioxAgents", self.frontend)
        failure = self.frontend.split("function renderAgentLoadError", 1)[1].split(
            "async function loadAioxAgents", 1
        )[0]
        self.assertIn("aiox-agents-unavailable", failure)
        self.assertNotIn("aiox-card", failure)
        for name in (*CANONICAL_NAMES, "ZEUS"):
            with self.subTest(name=name):
                self.assertNotIn(name, failure)

    def test_colors_depend_only_on_canonical_data_status(self):
        colors = {
            "idle": "#00e4ff",
            "working": "#00ff42",
            "waiting": "#ffc928",
            "error": "#ff456a",
        }
        for status, color in colors.items():
            with self.subTest(status=status):
                rule = re.search(
                    rf'\.aiox-card\[data-agent-status="{status}"\]\s*\{{([^}}]+)\}}',
                    self.index,
                )
                self.assertIsNotNone(rule)
                self.assertIn(f"--agent:{color}", rule.group(1).replace(" ", ""))
        fixed_dot = re.search(r"\.aiox-card\s*>\s*span\s*\{([^}]+)\}", self.index)
        self.assertIsNone(fixed_dot)

    def test_frontend_catalog_matches_backend_payload_and_excludes_zeus(self):
        agents = tuple(agent.to_dict() for agent in CANONICAL_AGENT_DEFINITIONS)
        self.assertEqual(len(agents), 8)
        self.assertEqual(tuple(agent["name"] for agent in agents), CANONICAL_NAMES)
        self.assertEqual({agent["status"] for agent in agents}, {"idle"})
        self.assertNotIn("ZEUS", {agent["name"] for agent in agents})


if __name__ == "__main__":
    unittest.main()
