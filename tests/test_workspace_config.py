from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path

import app.core.config as config


class WorkspaceConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_workspace = os.environ.pop("JARVIS_WORKSPACE_ROOT", None)
        importlib.reload(config)

    def tearDown(self) -> None:
        if self.original_workspace is None:
            os.environ.pop("JARVIS_WORKSPACE_ROOT", None)
        else:
            os.environ["JARVIS_WORKSPACE_ROOT"] = self.original_workspace
        importlib.reload(config)

    def test_windows_default_is_the_bounded_jarvis_workspace(self) -> None:
        self.assertEqual(config.WORKSPACE_ROOT, Path(r"D:\Jarvis").resolve())
        self.assertNotEqual(config.WORKSPACE_ROOT, Path("D:/").resolve())

    def test_official_subroots_are_derived_from_workspace_root(self) -> None:
        self.assertEqual(config.WORD_WORKSPACE, config.WORKSPACE_ROOT / "Word")
        self.assertEqual(config.EXCEL_WORKSPACE, config.WORKSPACE_ROOT / "Excel")
        self.assertEqual(config.POWERBI_WORKSPACE, config.WORKSPACE_ROOT / "Power BI")
        self.assertEqual(config.VSCODE_WORKSPACE, config.WORKSPACE_ROOT / "VS Code")

    def test_every_official_subroot_remains_inside_workspace_root(self) -> None:
        roots = (
            config.WORD_WORKSPACE,
            config.EXCEL_WORKSPACE,
            config.POWERBI_WORKSPACE,
            config.VSCODE_WORKSPACE,
        )

        for root in roots:
            with self.subTest(root=root):
                self.assertNotEqual(root.relative_to(config.WORKSPACE_ROOT), Path("."))

    def test_environment_override_rederives_every_subroot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            override = Path(temp_dir) / "External Jarvis Workspace"
            os.environ["JARVIS_WORKSPACE_ROOT"] = str(override)
            importlib.reload(config)

            expected_root = override.resolve()
            self.assertEqual(config.WORKSPACE_ROOT, expected_root)
            self.assertEqual(config.WORD_WORKSPACE, expected_root / "Word")
            self.assertEqual(config.EXCEL_WORKSPACE, expected_root / "Excel")
            self.assertEqual(config.POWERBI_WORKSPACE, expected_root / "Power BI")
            self.assertEqual(config.VSCODE_WORKSPACE, expected_root / "VS Code")

    def test_environment_override_rejects_an_entire_drive_root(self) -> None:
        os.environ["JARVIS_WORKSPACE_ROOT"] = "D:/"

        with self.assertRaisesRegex(ValueError, "volume inteiro"):
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
