"""Action segura e verificavel para criar documentos Word."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path, PureWindowsPath

from docx import Document
from pydantic import BaseModel, ConfigDict, Field

from app.actions.models import (
    ActionArtifact,
    ActionResult,
    ActionRisk,
    PersistencePolicy,
)
from app.actions.policy import PathAccess, PathPolicy
from app.actions.registry import ActionDefinition
from app.core.config import WORD_WORKSPACE


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class WordCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content: str
    title: str | None = None
    overwrite: bool = False


def _safe_output_path(
    filename: str,
    *,
    projects_root: Path,
    path_policy: PathPolicy,
) -> Path:
    raw_name = filename.strip()
    candidate = Path(raw_name)
    windows_candidate = PureWindowsPath(raw_name)
    if not raw_name:
        raise ValueError("Nome do arquivo Word e obrigatorio.")
    if candidate.is_absolute() or windows_candidate.is_absolute():
        raise ValueError("O nome do arquivo Word nao pode ser um caminho absoluto.")
    if "/" in raw_name or "\\" in raw_name:
        raise ValueError("O nome do arquivo Word nao pode conter diretorios.")
    if ".." in raw_name:
        raise ValueError("O nome do arquivo Word nao pode conter '..'.")
    if candidate.name != raw_name or windows_candidate.name != raw_name:
        raise ValueError("Somente um nome simples de arquivo Word e permitido.")
    if candidate.suffix.lower() != ".docx":
        raise ValueError("A extensao .docx e obrigatoria.")

    clean_name = _INVALID_FILENAME_CHARACTERS.sub("_", raw_name).strip().rstrip(". ")
    if not clean_name or Path(clean_name).suffix.lower() != ".docx":
        raise ValueError("Nome de arquivo Word invalido.")
    output_path = (projects_root / clean_name).resolve()
    return path_policy.validate(output_path, access=PathAccess.WRITE)


def _create_word_document(
    arguments: WordCreateInput,
    *,
    projects_root: Path,
    path_policy: PathPolicy,
) -> ActionResult:
    path = _safe_output_path(
        arguments.filename,
        projects_root=projects_root,
        path_policy=path_policy,
    )
    if path.exists() and not arguments.overwrite:
        raise FileExistsError(f"Arquivo Word ja existe: {path.name}")

    projects_root.mkdir(parents=True, exist_ok=True)
    document = Document()
    if arguments.title:
        document.add_heading(arguments.title, level=0)
    document.add_paragraph(arguments.content)
    document.save(path)
    size = path.stat().st_size
    return ActionResult(
        ok=True,
        action="word.create",
        summary="Documento Word criado e aguardando verificacao.",
        artifacts=[
            ActionArtifact(
                path=str(path),
                exists=path.is_file(),
                size=size,
                media_type=DOCX_MEDIA_TYPE,
            )
        ],
        data={"path": str(path), "title": arguments.title},
    )


def _verify_word_result(
    arguments: WordCreateInput,
    result: ActionResult,
    *,
    projects_root: Path,
    path_policy: PathPolicy,
) -> bool:
    if len(result.artifacts) != 1:
        return False
    artifact = result.artifacts[0]
    try:
        expected_path = _safe_output_path(
            arguments.filename,
            projects_root=projects_root,
            path_policy=path_policy,
        )
        path = path_policy.validate(artifact.path, access=PathAccess.WRITE)
        if (
            path != expected_path
            or path.suffix.lower() != ".docx"
            or not artifact.exists
            or not path.is_file()
            or path.stat().st_size <= 0
            or artifact.size != path.stat().st_size
            or result.data.get("path") != str(path)
        ):
            return False
        document = Document(path)
    except Exception:
        return False

    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    expected = ([arguments.title] if arguments.title else []) + [arguments.content]
    return paragraphs == expected


def create_word_definition(
    *,
    projects_root: Path = WORD_WORKSPACE,
) -> ActionDefinition:
    resolved_root = projects_root.resolve()
    path_policy = PathPolicy(write_roots=(resolved_root,))

    async def handler(arguments: WordCreateInput) -> ActionResult:
        return await asyncio.to_thread(
            _create_word_document,
            arguments,
            projects_root=resolved_root,
            path_policy=path_policy,
        )

    async def verifier(arguments: WordCreateInput, result: ActionResult) -> bool:
        return await asyncio.to_thread(
            _verify_word_result,
            arguments,
            result,
            projects_root=resolved_root,
            path_policy=path_policy,
        )

    return ActionDefinition(
        name="word.create",
        description="Criar documento Word",
        input_model=WordCreateInput,
        handler=handler,
        verifier=verifier,
        risk=ActionRisk.WRITE_FILE,
        confirmation_required=False,
        timeout=30.0,
        desktop_exclusive=False,
        persistence=PersistencePolicy.SANITIZED,
        allowed_sources=frozenset({"chat", "api"}),
    )
