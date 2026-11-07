"""Contrato bounded entre GET /api/obsidian/graph e o modo GRAFO do Cérebro 3.

Mesma convenção de tests/test_fastapi_agent_frontend.py: index.html manipula
`document` diretamente e não roda isolado sob node:test (sem jsdom), então a
verificação é estrutural sobre o texto do arquivo.
"""

from __future__ import annotations

import unittest

from app.core.config import PROJECT_ROOT


class ObsidianGraphFrontendContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = (PROJECT_ROOT / "public" / "index.html").read_text(
            encoding="utf-8"
        )

    def test_brain_modal_has_grafo_and_explorador_toggle(self) -> None:
        self.assertIn('id="brain-mode-toggle"', self.index)
        self.assertIn('data-mode="explorer"', self.index)
        self.assertIn('data-mode="graph"', self.index)
        self.assertIn(">EXPLORADOR<", self.index)
        self.assertIn(">GRAFO<", self.index)

    def test_explorer_mode_is_the_default(self) -> None:
        toggle = self.index.split('id="brain-mode-toggle"', 1)[1].split(
            "</div>", 1
        )[0]
        explorer_tag = toggle.split("<button", 2)[1]
        graph_tag = toggle.split("<button", 2)[2]
        self.assertIn('data-mode="explorer"', explorer_tag)
        self.assertIn("is-active", explorer_tag.split(">", 1)[0])
        self.assertIn('data-mode="graph"', graph_tag)
        self.assertNotIn("is-active", graph_tag.split(">", 1)[0])

    def test_frontend_consumes_the_graph_endpoint_exactly_once(self) -> None:
        self.assertEqual(self.index.count("fetch('/api/obsidian/graph')"), 1)
        self.assertIn("async function loadBrainGraphSafe", self.index)

    def test_existing_explorer_endpoints_are_untouched(self) -> None:
        self.assertIn("fetch('/api/obsidian/tree')", self.index)
        self.assertIn("/api/obsidian/note?path=", self.index)

    def test_node_click_reuses_the_existing_note_opening_mechanism(self) -> None:
        self.assertIn("function openBrainGraphNodeSafe", self.index)
        handler = self.index.split("function openBrainGraphNodeSafe", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("loadBrainNoteSafe", handler)
        # nao pode reimplementar um segundo renderer de Markdown
        self.assertNotIn("marked.parse", handler)

    def test_search_input_is_reused_not_duplicated(self) -> None:
        self.assertEqual(self.index.count('id="brain-search"'), 1)
        self.assertIn("applyBrainGraphSearchSafe", self.index)

    def test_category_filters_exist_and_are_bounded(self) -> None:
        self.assertIn('id="brain-filters"', self.index)
        self.assertIn("function renderBrainFiltersSafe", self.index)
        self.assertIn("function toggleBrainGraphFilter", self.index)

    def test_graph_panel_has_zoom_pan_and_reset(self) -> None:
        self.assertIn("id=\"brain-graph-svg\"", self.index)
        self.assertIn("addEventListener('wheel'", self.index)
        self.assertIn("pointerdown", self.index)
        self.assertIn('id="brain-graph-reset"', self.index)

    def test_no_new_cdn_dependency_was_introduced(self) -> None:
        graph_section_start = self.index.index("function createBrainGraphState")
        graph_section_end = self.index.index(
            "async function loadBrainGraphSafe"
        ) + len("async function loadBrainGraphSafe")
        graph_section = self.index[graph_section_start:graph_section_end]
        for forbidden in ("cdn.", "d3.", "cytoscape", "vis-network", "<script src="):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, graph_section)

    def test_no_parallel_agent_or_note_catalog_was_hardcoded(self) -> None:
        graph_section_start = self.index.index("function createBrainGraphState")
        graph_section_end = self.index.index("bindBrainGraphInteractionsSafe(")
        graph_section = self.index[graph_section_start:graph_section_end]
        for hardcoded_name in ("MORPHEUS", "Morpheus", "\"oracle\"", "'oracle'"):
            with self.subTest(hardcoded_name=hardcoded_name):
                self.assertNotIn(hardcoded_name, graph_section)

    def test_explorer_tree_rendering_functions_still_present(self) -> None:
        self.assertIn("function renderBrainTreeSafe", self.index)
        self.assertIn("async function loadBrainTreeSafe", self.index)
        self.assertIn("async function loadBrainNoteSafe", self.index)


if __name__ == "__main__":
    unittest.main()
