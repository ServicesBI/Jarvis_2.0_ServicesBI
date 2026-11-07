from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.actions.engine import ActionEngine
from app.actions.models import ActionRequest, ActionRisk, PersistencePolicy
from app.actions.registry import ActionRegistry
from app.main import create_app
from app.tasks.manager import TaskManager


def _module():
    return importlib.import_module("app.actions.file_resolve")


class WorkspaceFixture:
    def make_workspaces(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.word = base / "Word"
        self.excel = base / "Excel"
        self.powerbi = base / "Power BI"
        self.vscode = base / "VS Code"
        self.legacy = base / "Documents and Projects"
        for root in (self.word, self.excel, self.powerbi, self.vscode, self.legacy):
            root.mkdir()

    def close_workspaces(self) -> None:
        self.temp_dir.cleanup()

    def create(self, root: Path, name: str) -> Path:
        path = root / name
        path.write_bytes(b"controlled-test-file")
        return path

    def resolve(self, name: str):
        return _module().resolve_file_name(
            name,
            word_workspace=self.word,
            excel_workspace=self.excel,
            powerbi_workspace=self.powerbi,
        )


class FileResolveSchemaTests(unittest.TestCase):
    def test_schema_accepts_only_literal_name(self) -> None:
        module = _module()
        self.assertEqual(module.FileResolveInput(name="Planilha Jarvis").name, "Planilha Jarvis")
        for field in ("path", "root", "workspace", "application", "glob", "shell"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                module.FileResolveInput.model_validate({"name": "Planilha", field: "no"})

    def test_schema_rejects_paths_devices_and_wildcards(self) -> None:
        for name in ("folder/file.xlsx", r"folder\file.xlsx", "..", r"C:\file.xlsx", r"\\server\share\file.xlsx", r"\\?\UNC\server\share\file.xlsx", r"\\?\C:\file.xlsx", "*.xlsx"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                _module().FileResolveInput(name=name)


class FileResolveWorkspaceTests(WorkspaceFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.make_workspaces()

    def tearDown(self) -> None:
        self.close_workspaces()

    def test_each_extension_is_found_only_in_its_assigned_workspace(self) -> None:
        for root, filename, extension in (
            (self.word, "Relatorio.docx", ".docx"),
            (self.excel, "Planilha.xlsx", ".xlsx"),
            (self.excel, "Modelo.xlsm", ".xlsm"),
            (self.powerbi, "Dashboard Financeiro.pbix", ".pbix"),
        ):
            with self.subTest(filename=filename):
                self.create(root, filename)
                result = self.resolve(filename)
                self.assertEqual((result.status, result.path, result.extension), ("found", filename, extension))

    def test_explicit_extension_enumerates_only_assigned_workspace(self) -> None:
        module = _module()
        for name, only_root in {
            "Relatorio.docx": self.word,
            "Planilha.xlsx": self.excel,
            "Modelo.xlsm": self.excel,
            "Dashboard.pbix": self.powerbi,
        }.items():
            visited: list[Path] = []
            real_matcher = module._matching_candidates

            def recording_matcher(root: Path, requested: str, extensions):
                visited.append(root)
                return real_matcher(root, requested, extensions)

            with self.subTest(name=name), patch.object(module, "_matching_candidates", side_effect=recording_matcher):
                self.resolve(name)
                self.assertEqual(visited, [only_root.resolve()])

    def test_wrong_workspace_vscode_and_legacy_are_ignored(self) -> None:
        for root, filename in (
            (self.word, "Wrong Excel.xlsx"),
            (self.excel, "Wrong Word.docx"),
            (self.excel, "Wrong Power BI.pbix"),
            (self.vscode, "Ignored.docx"),
            (self.legacy, "Legacy.xlsx"),
        ):
            with self.subTest(filename=filename):
                self.create(root, filename)
                self.assertEqual(self.resolve(filename).status, "not_found")

    def test_extensionless_search_is_non_recursive_and_ambiguous_across_roots(self) -> None:
        self.create(self.excel, "Analise Financeira.xlsx")
        self.create(self.powerbi, "Analise Financeira.pbix")
        nested = self.word / "Antigos"
        nested.mkdir()
        (nested / "Analise Financeira.docx").write_bytes(b"nested")
        result = self.resolve("Analise Financeira")
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.candidates, ["Analise Financeira.pbix", "Analise Financeira.xlsx"])
        self.assertNotIn(str(Path(self.temp_dir.name)), str(result.model_dump()))

    def test_found_artifact_and_data_keep_only_sanitized_filename(self) -> None:
        module = _module()
        self.create(self.excel, "Planilha Jarvis.xlsx")
        definition = module.create_file_resolve_definition(word_workspace=self.word, excel_workspace=self.excel, powerbi_workspace=self.powerbi)
        result = __import__("asyncio").run(definition.handler(module.FileResolveInput(name="Planilha Jarvis")))
        self.assertEqual(result.data["path"], "Planilha Jarvis.xlsx")
        self.assertEqual(result.artifacts[0].path, "Planilha Jarvis.xlsx")
        self.assertNotIn(str(Path(self.temp_dir.name)), str(result.model_dump()))

    def test_symlink_escape_is_rejected_when_supported(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.docx"
        outside.write_bytes(b"outside")
        link = self.word / "Escape.docx"
        try:
            link.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest("Symlink indisponivel neste ambiente Windows")
        with self.assertRaises(PermissionError):
            self.resolve("Escape")


class FileResolveEngineTests(WorkspaceFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.make_workspaces()
        self.manager = TaskManager(Path(self.temp_dir.name) / "tasks.json")

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.close_workspaces()

    async def test_definition_preserves_verified_read_contract(self) -> None:
        module = _module()
        self.create(self.word, "Relatorio.docx")
        definition = module.create_file_resolve_definition(word_workspace=self.word, excel_workspace=self.excel, powerbi_workspace=self.powerbi)
        registry = ActionRegistry()
        registry.register(definition)
        submitted = ActionEngine(registry, self.manager).submit(ActionRequest(action="file.resolve", arguments={"name": "Relatorio"}, source="api"))
        finished = await self.manager.wait(submitted["task_id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["result"]["data"]["path"], "Relatorio.docx")
        self.assertEqual(definition.risk, ActionRisk.READ)
        self.assertEqual(definition.persistence, PersistencePolicy.SANITIZED)
        self.assertEqual(definition.allowed_sources, frozenset({"chat", "api"}))
        self.assertTrue(definition.requires_verification)


class FileResolveOverrideAndStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_environment_override_routes_extensions_and_restores_official_root(self) -> None:
        config = importlib.import_module("app.core.config")
        open_module = importlib.import_module("app.actions.file_open")
        resolve_module = _module()
        previous = os.environ.get("JARVIS_WORKSPACE_ROOT")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["JARVIS_WORKSPACE_ROOT"] = temp_dir
                config = importlib.reload(config)
                open_module = importlib.reload(open_module)
                resolve_module = importlib.reload(resolve_module)
                for root in (config.WORD_WORKSPACE, config.EXCEL_WORKSPACE, config.POWERBI_WORKSPACE, config.VSCODE_WORKSPACE):
                    root.mkdir()
                for root, filename in ((config.WORD_WORKSPACE, "Doc.docx"), (config.EXCEL_WORKSPACE, "Book.xlsx"), (config.EXCEL_WORKSPACE, "Macro.xlsm"), (config.POWERBI_WORKSPACE, "Model.pbix"), (config.VSCODE_WORKSPACE, "Ignored.docx")):
                    (root / filename).write_bytes(b"controlled")
                self.assertEqual(resolve_module.resolve_file_name("Doc").path, "Doc.docx")
                self.assertEqual(resolve_module.resolve_file_name("Book").path, "Book.xlsx")
                self.assertEqual(resolve_module.resolve_file_name("Macro").path, "Macro.xlsm")
                self.assertEqual(resolve_module.resolve_file_name("Model").path, "Model.pbix")
                self.assertEqual(resolve_module.resolve_file_name("Ignored").status, "not_found")
        finally:
            if previous is None:
                os.environ.pop("JARVIS_WORKSPACE_ROOT", None)
            else:
                os.environ["JARVIS_WORKSPACE_ROOT"] = previous
            config = importlib.reload(config)
            importlib.reload(open_module)
            importlib.reload(resolve_module)
        self.assertEqual(config.WORKSPACE_ROOT, Path(r"D:\Jarvis"))

    async def test_startup_registers_file_resolve_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            application = create_app(task_manager=manager)
            try:
                for source in ("chat", "api"):
                    definitions = application.state.action_registry.definitions_for(source)
                    self.assertEqual(sum(item.name == "file.resolve" for item in definitions), 1)
            finally:
                await manager.shutdown()


if __name__ == "__main__":
    unittest.main()
