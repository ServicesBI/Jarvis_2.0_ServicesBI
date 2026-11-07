from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.actions.engine import ActionEngine
from app.actions.models import ActionRequest, ActionRisk, PersistencePolicy
from app.actions.policy import PathPolicy
from app.actions.registry import ActionRegistry
from app.main import create_app
from app.tasks.manager import TaskManager


def _module():
    return importlib.import_module("app.actions.file_open")


class WorkspaceFixture:
    def make_workspaces(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.word, self.excel = base / "Word", base / "Excel"
        self.powerbi, self.vscode = base / "Power BI", base / "VS Code"
        self.legacy = base / "Documents and Projects"
        for root in (self.word, self.excel, self.powerbi, self.vscode, self.legacy):
            root.mkdir()

    def close_workspaces(self) -> None:
        self.temp_dir.cleanup()

    def create(self, root: Path, name: str) -> Path:
        path = root / name
        path.write_bytes(b"controlled-test-file")
        return path

    def validate(self, path: str | Path) -> Path:
        return _module().validate_file_path(path, word_workspace=self.word, excel_workspace=self.excel, powerbi_workspace=self.powerbi)


class FileOpenSchemaAndDefinitionTests(unittest.TestCase):
    def test_schema_accepts_only_path(self) -> None:
        module = _module()
        self.assertEqual(module.FileOpenInput(path="Relatorio.docx").path, "Relatorio.docx")
        for field in ("root", "workspace", "application", "executable", "url", "args"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                module.FileOpenInput.model_validate({"path": "Relatorio.docx", field: "no"})

    def test_definition_preserves_desktop_contract(self) -> None:
        definition = _module().create_file_open_definition()
        self.assertEqual(definition.risk, ActionRisk.DESKTOP)
        self.assertFalse(definition.confirmation_required)
        self.assertTrue(definition.desktop_exclusive)
        self.assertEqual(definition.allowed_sources, frozenset({"chat", "api"}))
        self.assertEqual(definition.persistence, PersistencePolicy.SANITIZED)
        self.assertTrue(definition.requires_verification)


class FileOpenWorkspacePolicyTests(WorkspaceFixture, unittest.TestCase):
    def setUp(self) -> None:
        self.make_workspaces()

    def tearDown(self) -> None:
        self.close_workspaces()

    def test_each_extension_uses_only_its_assigned_read_root(self) -> None:
        module = _module()
        for root, filename in ((self.word, "Relatorio.docx"), (self.excel, "Planilha.xlsx"), (self.excel, "Modelo.xlsm"), (self.powerbi, "Dashboard.pbix")):
            with self.subTest(filename=filename):
                path = self.create(root, filename)
                policies: list[PathPolicy] = []
                real_policy = module.PathPolicy

                def recording_policy(*, read_roots=(), write_roots=()):
                    policy = real_policy(read_roots=read_roots, write_roots=write_roots)
                    policies.append(policy)
                    return policy

                with patch.object(module, "PathPolicy", side_effect=recording_policy):
                    resolved = self.validate(filename)
                self.assertEqual(resolved, path.resolve())
                self.assertEqual(len(policies), 1)
                self.assertEqual(policies[0].read_roots, (root.resolve(),))

    def test_wrong_workspace_vscode_legacy_and_workspace_parent_are_rejected(self) -> None:
        for path in (
            self.create(self.word, "Wrong.xlsx"),
            self.create(self.excel, "Wrong.docx"),
            self.create(self.excel, "Wrong.pbix"),
            self.create(self.vscode, "Ignored.docx"),
            self.create(self.legacy, "Legacy.xlsx"),
            self.create(Path(self.temp_dir.name), "Workspace Parent.docx"),
        ):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.validate(path)

    def test_traversal_missing_directory_unc_and_device_paths_are_rejected(self) -> None:
        directory = self.word / "folder.docx"
        directory.mkdir()
        for path, error in (("../outside.docx", (PermissionError, FileNotFoundError)), ("missing.docx", FileNotFoundError), (directory, IsADirectoryError), (r"\\server\share\arquivo.docx", PermissionError), (r"\\?\UNC\server\share\arquivo.docx", PermissionError), (r"\\?\C:\Windows\arquivo.docx", PermissionError), (r"\\.\C:\Windows\arquivo.docx", PermissionError)):
            with self.subTest(path=path), self.assertRaises(error):
                self.validate(path)

    def test_symlink_escape_is_rejected_when_supported(self) -> None:
        outside = Path(self.temp_dir.name) / "outside.docx"
        outside.write_bytes(b"outside")
        link = self.word / "Escape.docx"
        try:
            link.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest("Symlink indisponivel neste ambiente Windows")
        with self.assertRaises(PermissionError):
            self.validate(link)


class FileOpenApplicationAndLauncherTests(unittest.TestCase):
    def test_extension_mapping_is_closed(self) -> None:
        module = _module()
        for filename, application in {"report.docx": "word", "book.xlsx": "excel", "macro.xlsm": "excel", "model.pbix": "powerbi"}.items():
            self.assertEqual(module.application_for_file(Path(filename)), application)
        for suffix in (".exe", ".py", ".url", ".txt", ""):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                module.application_for_file(Path(f"payload{suffix}"))

    def test_launcher_uses_two_structured_arguments_and_shell_false(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temp_dir:
            executable, document = Path(temp_dir) / "PBIDesktop.exe", Path(temp_dir) / "Dashboard.pbix"
            executable.write_bytes(b"MZ")
            document.write_bytes(b"pbix")
            with patch.object(module.subprocess, "Popen") as popen:
                module.launch_file(executable, document)
            popen.assert_called_once_with([str(executable.resolve()), str(document.resolve())], shell=False, close_fds=True)


class FileOpenEngineTests(WorkspaceFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.make_workspaces()
        self.manager = TaskManager(Path(self.temp_dir.name) / "tasks.json")

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.close_workspaces()

    async def test_each_extension_resolves_fixed_application_and_sanitizes_result(self) -> None:
        module = _module()
        for root, filename, application, executable_name in ((self.word, "Relatorio.docx", "word", "WINWORD.EXE"), (self.excel, "Planilha.xlsx", "excel", "EXCEL.EXE"), (self.excel, "Modelo.xlsm", "excel", "EXCEL.EXE"), (self.powerbi, "Dashboard.pbix", "powerbi", "PBIDesktop.exe")):
            with self.subTest(filename=filename):
                self.create(root, filename)
                executable = Path(self.temp_dir.name) / executable_name
                executable.write_bytes(b"MZ")
                resolved_applications: list[str] = []
                launches: list[tuple[Path, Path]] = []

                def resolver(requested: str):
                    resolved_applications.append(requested)
                    return module.ExecutableResolution(requested, executable, "test")

                definition = module.create_file_open_definition(word_workspace=self.word, excel_workspace=self.excel, powerbi_workspace=self.powerbi, resolver=resolver, launcher=lambda exe, path: launches.append((exe, path)), process_snapshot=lambda _resolution: {42}, verification_attempts=1, verification_delay=0)
                registry = ActionRegistry()
                registry.register(definition)
                submitted = ActionEngine(registry, self.manager).submit(ActionRequest(action="file.open", arguments={"path": filename}, source="api"))
                finished = await self.manager.wait(submitted["task_id"])
                self.assertEqual(finished["status"], "completed")
                self.assertEqual(resolved_applications, [application])
                self.assertEqual(len(launches), 1)
                self.assertEqual(finished["result"]["data"]["file"], filename)
                self.assertEqual(finished["result"]["artifacts"][0]["path"], filename)
                self.assertNotIn(str(Path(self.temp_dir.name)), str(finished["result"]))


class FileOpenStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_registers_file_open_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            application = create_app(task_manager=manager)
            try:
                for source in ("chat", "api"):
                    definitions = application.state.action_registry.definitions_for(source)
                    self.assertEqual(sum(item.name == "file.open" for item in definitions), 1)
            finally:
                await manager.shutdown()


if __name__ == "__main__":
    unittest.main()
