"""Resolucao bounded de filenames nas subroots oficiais autorizadas."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.actions.file_open import EXTENSION_APPLICATIONS, EXTENSION_MEDIA_TYPES
from app.actions.models import ActionArtifact, ActionResult, ActionRisk, PersistencePolicy
from app.actions.policy import PathAccess, PathPolicy
from app.actions.registry import ActionDefinition
from app.core.config import EXCEL_WORKSPACE, POWERBI_WORKSPACE, WORD_WORKSPACE


class FileResolveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_literal_filename(cls, value: str) -> str:
        name = value.strip()
        if not name or name in {".", ".."} or "/" in name or "\\" in name or ":" in name or any(marker in name for marker in ("*", "?", "[", "]")):
            raise ValueError("name deve ser um filename literal, sem path ou wildcard.")
        return name


class FileResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["found", "not_found", "ambiguous"]
    filename: str | None = None
    path: str | None = None
    extension: str | None = None
    candidates: list[str] = Field(default_factory=list)


def _workspace_specs(
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
) -> tuple[tuple[Path, frozenset[str]], ...]:
    return (
        (Path(word_workspace or WORD_WORKSPACE).resolve(), frozenset({".docx"})),
        (Path(excel_workspace or EXCEL_WORKSPACE).resolve(), frozenset({".xlsx", ".xlsm"})),
        (Path(powerbi_workspace or POWERBI_WORKSPACE).resolve(), frozenset({".pbix"})),
    )


def _matching_candidates(root: Path, name: str, extensions: frozenset[str]) -> tuple[Path, ...]:
    requested = name.casefold()
    requested_suffix = Path(name).suffix.casefold()
    matches: list[Path] = []
    for candidate in root.iterdir():
        if not candidate.is_file() or candidate.suffix.casefold() not in extensions:
            continue
        matched = candidate.name.casefold() == requested if requested_suffix else candidate.stem.casefold() == requested
        if matched:
            matches.append(candidate)
    return tuple(matches)


def resolve_file_name(
    name: str,
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
) -> FileResolution:
    validated_name = FileResolveInput(name=name).name
    requested_suffix = Path(validated_name).suffix.casefold()
    specs = _workspace_specs(word_workspace=word_workspace, excel_workspace=excel_workspace, powerbi_workspace=powerbi_workspace)
    if requested_suffix:
        specs = tuple((root, extensions) for root, extensions in specs if requested_suffix in extensions)
    candidates: list[Path] = []
    for root, extensions in specs:
        policy = PathPolicy(read_roots=(root,))
        candidates.extend(policy.validate(candidate, access=PathAccess.READ) for candidate in _matching_candidates(root, validated_name, extensions))
    candidates.sort(key=lambda item: (item.name.casefold(), item.name))
    filenames = [candidate.name for candidate in candidates]
    if not candidates:
        return FileResolution(status="not_found")
    if len(candidates) > 1:
        return FileResolution(status="ambiguous", candidates=filenames)
    candidate = candidates[0]
    return FileResolution(status="found", filename=candidate.name, path=candidate.name, extension=candidate.suffix.casefold())


def _artifact_for_resolution(resolution: FileResolution, specs: tuple[tuple[Path, frozenset[str]], ...]) -> list[ActionArtifact]:
    if resolution.status != "found" or resolution.path is None or resolution.extension is None:
        return []
    root = next(root for root, extensions in specs if resolution.extension in extensions)
    path = root / resolution.path
    return [ActionArtifact(path=resolution.path, exists=path.is_file(), size=path.stat().st_size, media_type=EXTENSION_MEDIA_TYPES[resolution.extension])]


def create_file_resolve_definition(
    *,
    word_workspace: Path | None = None,
    excel_workspace: Path | None = None,
    powerbi_workspace: Path | None = None,
) -> ActionDefinition:
    specs = _workspace_specs(word_workspace=word_workspace, excel_workspace=excel_workspace, powerbi_workspace=powerbi_workspace)

    async def handler(arguments: FileResolveInput) -> ActionResult:
        resolution = resolve_file_name(arguments.name, word_workspace=word_workspace, excel_workspace=excel_workspace, powerbi_workspace=powerbi_workspace)
        return ActionResult(ok=True, action="file.resolve", summary=f"Resolucao concluida com status {resolution.status}.", artifacts=_artifact_for_resolution(resolution, specs), data=resolution.model_dump(mode="json"))

    async def verifier(arguments: FileResolveInput, result: ActionResult) -> bool:
        try:
            current = resolve_file_name(arguments.name, word_workspace=word_workspace, excel_workspace=excel_workspace, powerbi_workspace=powerbi_workspace)
            artifacts = _artifact_for_resolution(current, specs)
        except (OSError, ValueError):
            return False
        return result.data == current.model_dump(mode="json") and result.artifacts == artifacts

    return ActionDefinition(
        name="file.resolve",
        description="Resolver filename autorizado nas subroots oficiais",
        input_model=FileResolveInput,
        handler=handler,
        verifier=verifier,
        risk=ActionRisk.READ,
        confirmation_required=False,
        timeout=5.0,
        desktop_exclusive=False,
        persistence=PersistencePolicy.SANITIZED,
        allowed_sources=frozenset({"chat", "api"}),
    )
