from __future__ import annotations

import unittest

from app.agents.models import AgentDefinition, AgentStatus
from app.agents.registry import (
    DuplicateAgentError,
    UnknownAgentError,
    AgentRegistry,
    create_agent_registry,
)


EXPECTED_IDS = (
    "morpheus",
    "oracle",
    "nikita",
    "athena",
    "neo",
    "hephaestus",
    "apollo",
    "trinity",
)
LEGACY_AND_NON_AGENT_IDS = {
    "orion", "morgan", "pax", "river", "craft", "dara", "aria", "dex",
    "sage", "gage", "quinn", "luma", "uma", "zeus", "conclave",
}


class AgentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = create_agent_registry()

    def test_catalog_has_exact_canonical_ids_in_stable_order(self) -> None:
        self.assertEqual(
            tuple(agent.id for agent in self.registry.list_agents()), EXPECTED_IDS
        )

    def test_all_agents_start_idle_and_exclude_legacy_non_agents(self) -> None:
        agents = self.registry.list_agents()
        self.assertTrue(all(agent.status is AgentStatus.IDLE for agent in agents))
        self.assertTrue(LEGACY_AND_NON_AGENT_IDS.isdisjoint(agent.id for agent in agents))

    def test_lookup_neo_returns_software_engineer(self) -> None:
        neo = self.registry.get("neo")
        self.assertEqual((neo.name, neo.role), ("NEO", "SOFTWARE ENGINEER"))

    def test_lookup_unknown_id_raises_explicit_error(self) -> None:
        with self.assertRaisesRegex(UnknownAgentError, "Unknown agent id"):
            self.registry.get("missing")

    def test_duplicate_id_is_rejected(self) -> None:
        duplicate = AgentDefinition(
            id="neo",
            name="OTHER NEO",
            role="SOFTWARE ENGINEER",
            description="Duplicate used to prove registry validation.",
            status=AgentStatus.IDLE,
            canonical_persona="obsidian-template/Agentes/Neo — Software Engineer.md",
        )
        with self.assertRaisesRegex(DuplicateAgentError, "Duplicate agent id: neo"):
            AgentRegistry((self.registry.get("neo"), duplicate))


if __name__ == "__main__":
    unittest.main()
