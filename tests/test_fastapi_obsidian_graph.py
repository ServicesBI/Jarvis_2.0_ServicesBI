"""RED/GREEN do grafo do Obsidian: GET /api/obsidian/graph.

Cobre as regras de parsing de wikilink com um vault sintetico e temporario
(isolado, sem depender do conteudo real do vault mudar) e faz uma checagem
minima contra o vault real para provar que o grafo reflete o vault de fato.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.workspace import _build_graph
from app.core.config import PROJECT_ROOT
from app.main import create_app
from app.tasks.manager import TaskManager


def _write(vault: Path, relative: str, content: str) -> None:
    target = vault / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class ObsidianGraphParsingTests(unittest.TestCase):
    """Unit-level: exercita _build_graph diretamente contra um vault temporario."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _graph(self) -> dict:
        return _build_graph(self.vault)

    def test_nodes_come_from_markdown_files(self) -> None:
        _write(self.vault, "Arquitetura.md", "conteudo qualquer")
        _write(self.vault, "Agentes/Neo — Software Engineer.md", "conteudo")
        graph = self._graph()

        ids = {node["id"] for node in graph["nodes"]}
        self.assertIn("Arquitetura.md", ids)
        self.assertIn("Agentes/Neo — Software Engineer.md", ids)
        self.assertEqual(graph["count"], len(graph["nodes"]))

    def test_explicit_path_wikilink_resolves(self) -> None:
        _write(self.vault, "Agentes/Neo — Software Engineer.md", "neo")
        _write(
            self.vault,
            "AIOX-CORE.md",
            "veja [[Agentes/Neo — Software Engineer]]",
        )
        graph = self._graph()

        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(
            ("AIOX-CORE.md", "Agentes/Neo — Software Engineer.md"), edges
        )

    def test_alias_does_not_change_the_resolved_target(self) -> None:
        _write(self.vault, "Arquitetura.md", "conteudo")
        _write(
            self.vault, "Nota.md", "[[Arquitetura|Arquitetura do Jarvis]]"
        )
        graph = self._graph()

        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(("Nota.md", "Arquitetura.md"), edges)
        titles = {node["id"]: node["title"] for node in graph["nodes"]}
        self.assertEqual(titles["Arquitetura.md"], "Arquitetura")

    def test_heading_link_resolves_to_the_base_note(self) -> None:
        _write(self.vault, "Arquitetura.md", "# Stack\nconteudo")
        _write(self.vault, "Nota.md", "[[Arquitetura#Stack]]")
        graph = self._graph()

        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(("Nota.md", "Arquitetura.md"), edges)

    def test_bare_stem_link_resolves_deterministically(self) -> None:
        _write(self.vault, "Agentes/Neo — Software Engineer.md", "neo")
        _write(self.vault, "Nota.md", "[[Neo — Software Engineer]]")
        graph = self._graph()

        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(
            ("Nota.md", "Agentes/Neo — Software Engineer.md"), edges
        )

    def test_case_insensitive_resolution(self) -> None:
        _write(self.vault, "Arquitetura.md", "conteudo")
        _write(self.vault, "Nota.md", "[[arquitetura]]")
        graph = self._graph()

        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(("Nota.md", "Arquitetura.md"), edges)

    def test_duplicate_wikilinks_produce_a_single_edge(self) -> None:
        _write(self.vault, "Arquitetura.md", "conteudo")
        _write(
            self.vault,
            "Nota.md",
            "[[Arquitetura]] e de novo [[Arquitetura]] e mais [[Arquitetura|alias]]",
        )
        graph = self._graph()

        edges = [
            (e["source"], e["target"])
            for e in graph["edges"]
            if e["source"] == "Nota.md" and e["target"] == "Arquitetura.md"
        ]
        self.assertEqual(len(edges), 1)

    def test_self_loop_is_ignored(self) -> None:
        _write(self.vault, "Nota.md", "[[Nota]]")
        graph = self._graph()

        self_edges = [
            e
            for e in graph["edges"]
            if e["source"] == "Nota.md" and e["target"] == "Nota.md"
        ]
        self.assertEqual(self_edges, [])

    def test_unresolved_wikilink_becomes_exists_false_node(self) -> None:
        _write(self.vault, "Nota.md", "[[Nota Que Nao Existe]]")
        graph = self._graph()

        unresolved = [n for n in graph["nodes"] if n["exists"] is False]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["title"], "Nota Que Nao Existe")
        edges = {(e["source"], e["target"]) for e in graph["edges"]}
        self.assertIn(("Nota.md", unresolved[0]["id"]), edges)

    def test_broken_link_never_breaks_the_endpoint(self) -> None:
        _write(self.vault, "Nota.md", "[[Isso Nao Existe]] [[Nem Isso]]")
        graph = self._graph()  # nao deve levantar excecao
        self.assertGreaterEqual(graph["count"], 1)

    def test_category_derived_from_top_level_folder(self) -> None:
        _write(self.vault, "Agentes/Neo — Software Engineer.md", "neo")
        _write(self.vault, "Arquitetura.md", "raiz")
        graph = self._graph()

        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(
            by_id["Agentes/Neo — Software Engineer.md"]["category"], "Agentes"
        )
        self.assertEqual(by_id["Arquitetura.md"]["category"], "root")

    def test_no_agent_runtime_data_leaks_into_the_graph(self) -> None:
        _write(self.vault, "Agentes/Neo — Software Engineer.md", "neo")
        graph = self._graph()

        payload = json.dumps(graph)
        for forbidden in ("status", "idle", "working", "agent_registry"):
            self.assertNotIn(forbidden, payload.lower())

    def test_missing_vault_returns_empty_graph_without_error(self) -> None:
        graph = _build_graph(self.vault / "does-not-exist")
        self.assertEqual(graph, {"nodes": [], "edges": [], "count": 0, "edge_count": 0})


class ObsidianGraphHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        # create_app() sem task_manager= constroi um TaskManager real ligado
        # a system/task-state.json (le/reconcilia esse arquivo no __init__),
        # mesmo quando o teste so exercita rotas /api/obsidian/*.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_manager = TaskManager(Path(self.temp_dir.name) / "task-state.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _client(self) -> TestClient:
        return TestClient(create_app(task_manager=self.task_manager))

    def test_endpoint_returns_nodes_and_edges_shape(self) -> None:
        with self._client() as client:
            response = client.get("/api/obsidian/graph")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("nodes", body)
        self.assertIn("edges", body)
        self.assertEqual(body["count"], len(body["nodes"]))
        self.assertEqual(body["edge_count"], len(body["edges"]))

    def test_endpoint_uses_obsidian_vault_setting_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir)
            _write(vault, "Isolado.md", "conteudo isolado")
            with patch.dict(os.environ, {"OBSIDIAN_VAULT": str(vault)}):
                with self._client() as client:
                    response = client.get("/api/obsidian/graph")
            body = response.json()
            ids = {node["id"] for node in body["nodes"]}
            self.assertEqual(ids, {"Isolado.md"})

    def test_real_vault_contains_the_expected_canonical_notes(self) -> None:
        with self._client() as client:
            response = client.get("/api/obsidian/graph")
        ids = {node["id"] for node in response.json()["nodes"]}

        for expected in (
            "Cerebro 1 — Claude.md",
            "Cerebro 2 — Mega-Brain.md",
            "Cerebro 3 — Obsidian.md",
            "AIOX-CORE — Agentes.md",
            "Agentes/Morpheus — Orchestrator.md",
            "Agentes/Neo — Software Engineer.md",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, ids)

    def test_real_vault_has_a_real_edge_from_aiox_core_to_neo(self) -> None:
        with self._client() as client:
            response = client.get("/api/obsidian/graph")
        edges = {(e["source"], e["target"]) for e in response.json()["edges"]}
        self.assertIn(
            (
                "AIOX-CORE — Agentes.md",
                "Agentes/Neo — Software Engineer.md",
            ),
            edges,
        )

    def test_real_vault_still_contains_historical_agent_notes(self) -> None:
        with self._client() as client:
            response = client.get("/api/obsidian/graph")
        ids = {node["id"] for node in response.json()["nodes"]}
        self.assertIn("Agentes/Orion — AIOS Master.md", ids)

    def test_graph_endpoint_is_read_only_no_write_route(self) -> None:
        with self._client() as client:
            response = client.post("/api/obsidian/graph", json={})
        self.assertEqual(response.status_code, 405)

    def test_explorer_tree_endpoint_still_works(self) -> None:
        with self._client() as client:
            response = client.get("/api/obsidian/tree")
        self.assertEqual(response.status_code, 200)
        self.assertIn("tree", response.json())


if __name__ == "__main__":
    unittest.main()
