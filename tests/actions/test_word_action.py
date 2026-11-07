from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.actions.models import ActionResult
from app.actions.word import (
    DOCX_MEDIA_TYPE,
    WordCreateInput,
    create_word_definition,
)
import app.actions.word as word_module
import app.core.config as config_module


class WordWorkspaceDefaultTests(unittest.TestCase):
    def test_workspace_override_confines_default_to_word_subroot(self) -> None:
        filename = "TDD Word Workspace Root Migration.docx"
        original_environment = os.environ.get("JARVIS_WORKSPACE_ROOT")
        old_path = (
            config_module.PROJECT_ROOT / "Documents and Projects" / filename
        ).resolve()
        self.assertFalse(old_path.exists(), "O fixture exclusivo ja existe na root antiga")

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "Workspace Override"
            expected_root = (workspace_root / "Word").resolve()

            try:
                os.environ["JARVIS_WORKSPACE_ROOT"] = str(workspace_root)
                importlib.reload(config_module)
                importlib.reload(word_module)
                real_path_policy = word_module.PathPolicy

                class RecordingPathPolicy(real_path_policy):
                    instances: list["RecordingPathPolicy"] = []

                    def __init__(self, **kwargs):
                        super().__init__(**kwargs)
                        self.instances.append(self)

                with patch.object(word_module, "PathPolicy", RecordingPathPolicy):
                    definition = word_module.create_word_definition()
                    payload = word_module.WordCreateInput(
                        filename=filename,
                        content="Conteudo do teste de workspace Word.",
                    )
                    result = asyncio.run(definition.handler(payload))

                created = Path(result.artifacts[0].path).resolve()
                self.assertEqual(created, expected_root / filename)
                self.assertTrue(created.is_file())
                self.assertEqual(len(RecordingPathPolicy.instances), 1)
                self.assertEqual(
                    RecordingPathPolicy.instances[0].write_roots,
                    (expected_root,),
                )
                self.assertNotEqual(
                    RecordingPathPolicy.instances[0].write_roots,
                    (workspace_root.resolve(),),
                )
                self.assertFalse(old_path.exists())
            finally:
                if old_path.is_file():
                    old_path.unlink()
                if original_environment is None:
                    os.environ.pop("JARVIS_WORKSPACE_ROOT", None)
                else:
                    os.environ["JARVIS_WORKSPACE_ROOT"] = original_environment
                importlib.reload(config_module)
                importlib.reload(word_module)

        self.assertEqual(
            os.environ.get("JARVIS_WORKSPACE_ROOT"), original_environment
        )
        self.assertEqual(word_module.WORD_WORKSPACE, config_module.WORD_WORKSPACE)


class WordActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.projects_dir = Path(self.temp_dir.name) / "Documents and Projects"
        self.definition = create_word_definition(projects_root=self.projects_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def execute(self, **arguments: object) -> tuple[WordCreateInput, ActionResult]:
        payload = WordCreateInput.model_validate(arguments)
        result = asyncio.run(self.definition.handler(payload))
        return payload, result

    def verify(self, payload: WordCreateInput, result: ActionResult) -> bool:
        return asyncio.run(self.definition.verifier(payload, result))

    def test_creates_valid_docx_with_expected_content_and_artifact(self) -> None:
        payload, result = self.execute(filename="Relatorio.docx", content="Conteudo real")

        artifact = result.artifacts[0]
        path = Path(artifact.path)
        self.assertTrue(result.ok)
        self.assertEqual(result.action, "word.create")
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(path, (self.projects_dir / "Relatorio.docx").resolve())
        self.assertTrue(artifact.exists)
        self.assertEqual(artifact.size, path.stat().st_size)
        self.assertEqual(artifact.media_type, DOCX_MEDIA_TYPE)
        self.assertTrue(self.verify(payload, result))

    def test_creates_docx_with_title_and_persisted_content(self) -> None:
        from docx import Document

        payload, result = self.execute(
            filename="Com titulo.docx",
            title="Titulo esperado",
            content="Corpo esperado",
        )

        document = Document(result.artifacts[0].path)
        self.assertEqual(
            [paragraph.text for paragraph in document.paragraphs],
            ["Titulo esperado", "Corpo esperado"],
        )
        self.assertEqual(document.paragraphs[0].style.name, "Title")
        self.assertTrue(self.verify(payload, result))

    def test_sanitizes_invalid_filename_characters(self) -> None:
        payload, result = self.execute(filename="Relatorio?.docx", content="Seguro")

        self.assertEqual(Path(result.artifacts[0].path).name, "Relatorio_.docx")
        self.assertTrue(self.verify(payload, result))

    def test_rejects_non_docx_extension(self) -> None:
        with self.assertRaises(ValueError):
            self.execute(filename="relatorio.txt", content="Nao gravar")

    def test_rejects_absolute_path(self) -> None:
        absolute = str((Path(self.temp_dir.name) / "fora.docx").resolve())
        with self.assertRaises(ValueError):
            self.execute(filename=absolute, content="Nao gravar")

    def test_rejects_subdirectory(self) -> None:
        with self.assertRaises(ValueError):
            self.execute(filename="pasta/relatorio.docx", content="Nao gravar")
        with self.assertRaises(ValueError):
            self.execute(filename=r"pasta\relatorio.docx", content="Nao gravar")

    def test_rejects_dot_dot_and_path_traversal(self) -> None:
        for filename in ("..", "../fora.docx", r"..\fora.docx", "relatorio..docx"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.execute(filename=filename, content="Nao gravar")

    def test_existing_file_requires_explicit_overwrite(self) -> None:
        _, original = self.execute(filename="existente.docx", content="Original")
        original_bytes = Path(original.artifacts[0].path).read_bytes()

        with self.assertRaises(FileExistsError):
            self.execute(filename="existente.docx", content="Substituto")

        self.assertEqual(Path(original.artifacts[0].path).read_bytes(), original_bytes)

    def test_overwrite_true_replaces_existing_file_after_validation(self) -> None:
        from docx import Document

        self.execute(filename="existente.docx", content="Original")

        payload, replacement = self.execute(
            filename="existente.docx",
            content="Substituto",
            overwrite=True,
        )

        self.assertTrue(self.verify(payload, replacement))
        document = Document(replacement.artifacts[0].path)
        self.assertEqual(
            [paragraph.text for paragraph in document.paragraphs],
            ["Substituto"],
        )

    def test_verifier_rejects_missing_and_corrupt_files(self) -> None:
        payload, result = self.execute(filename="verificar.docx", content="Esperado")
        path = Path(result.artifacts[0].path)
        path.unlink()
        self.assertFalse(self.verify(payload, result))

        path.write_bytes(b"not a docx")
        corrupt = result.model_copy(
            update={
                "artifacts": [
                    result.artifacts[0].model_copy(
                        update={"exists": True, "size": path.stat().st_size}
                    )
                ]
            }
        )
        self.assertFalse(self.verify(payload, corrupt))

    def test_verifier_rejects_document_without_expected_content(self) -> None:
        from docx import Document

        payload, result = self.execute(filename="alterado.docx", content="Esperado")
        changed = Document()
        changed.add_paragraph("Outro conteudo")
        changed.save(result.artifacts[0].path)
        changed_result = result.model_copy(
            update={
                "artifacts": [
                    result.artifacts[0].model_copy(
                        update={"size": Path(result.artifacts[0].path).stat().st_size}
                    )
                ]
            }
        )

        self.assertFalse(self.verify(payload, changed_result))

    def test_path_policy_confines_output_to_documents_and_projects(self) -> None:
        payload, result = self.execute(filename="seguro.docx", content="Seguro")
        path = Path(result.artifacts[0].path).resolve()

        self.assertIn(self.projects_dir.resolve(), path.parents)
        self.assertTrue(self.verify(payload, result))


class WordActionDefinitionTests(unittest.TestCase):
    def test_definition_matches_action_engine_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            definition = create_word_definition(
                projects_root=Path(temp_dir) / "Documents and Projects"
            )

        self.assertEqual(definition.name, "word.create")
        self.assertEqual(definition.risk.value, "write_file")
        self.assertFalse(definition.confirmation_required)
        self.assertTrue(definition.requires_verification)
        self.assertEqual(definition.persistence.value, "sanitized")
        self.assertEqual(definition.allowed_sources, frozenset({"chat", "api"}))

    def test_schema_is_closed_and_has_approved_defaults(self) -> None:
        payload = WordCreateInput(filename="arquivo.docx", content="Conteudo")
        self.assertIsNone(payload.title)
        self.assertFalse(payload.overwrite)

        with self.assertRaises(ValidationError):
            WordCreateInput.model_validate(
                {"filename": "arquivo.docx", "content": "Conteudo", "extra": True}
            )


if __name__ == "__main__":
    unittest.main()
