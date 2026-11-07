"""Definição estruturada da action excel.create sobre a automação existente."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, Field

from app.automation import excel as excel_automation
from app.actions.models import (
    ActionArtifact,
    ActionResult,
    ActionRisk,
    PersistencePolicy,
)
from app.actions.policy import PathAccess, PathPolicy
from app.actions.registry import ActionDefinition
from app.automation.excel import create_workbook


XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class ExcelCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(default="Planilha Jarvis.xlsx", min_length=1, max_length=255)
    headers: list[Any] | None = Field(default=None, min_length=1, max_length=50)
    rows: list[Any] | None = Field(default=None, max_length=10000)
    sheet: str | None = Field(default=None, min_length=1, max_length=255)
    openFile: bool = False


async def create_excel(arguments: ExcelCreateInput) -> ActionResult:
    payload = arguments.model_dump(exclude_none=True)
    result = await create_workbook(payload)
    path = str(result.get("path") or "")
    size = int(result.get("size") or 0)
    return ActionResult(
        ok=result.get("ok") is True,
        action="excel.create",
        summary="Planilha Excel criada e verificada.",
        artifacts=[
            ActionArtifact(
                path=path,
                exists=bool(path) and Path(path).is_file(),
                size=size,
                media_type=XLSX_MEDIA_TYPE,
            )
        ],
        data={
            "path": path,
            "sheet": result.get("sheet"),
            "headers": result.get("headers"),
            "rows": result.get("rows"),
            "formulas": result.get("formulas"),
            "opened": result.get("opened") is True,
        },
        error=None if result.get("ok") is True else "Workbook não foi criado.",
    )


def _verify_excel_result(
    arguments: ExcelCreateInput,
    result: ActionResult,
) -> bool:
    if len(result.artifacts) != 1:
        return False
    artifact = result.artifacts[0]
    try:
        expected_path = excel_automation._safe_output_path(arguments.filename)
        path = PathPolicy(
            write_roots=(excel_automation.PROJECTS_DIR.resolve(),)
        ).validate(
            artifact.path,
            access=PathAccess.WRITE,
        )
    except Exception:
        return False
    if (
        path != expected_path
        or not artifact.exists
        or path.suffix.lower() != ".xlsx"
        or not path.is_file()
        or path.stat().st_size <= 0
        or artifact.size != path.stat().st_size
        or artifact.media_type != XLSX_MEDIA_TYPE
        or result.data.get("path") != str(path)
    ):
        return False
    payload = arguments.model_dump(exclude_none=True)
    expected_sheet, expected_headers, expected_rows = (
        excel_automation.expected_workbook_content(payload)
    )
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except Exception:
        return False
    try:
        if workbook.sheetnames != [expected_sheet]:
            return False
        sheet = workbook[expected_sheet]
        actual_rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        expected_matrix = [expected_headers, *expected_rows]
        width = max((len(row) for row in expected_matrix), default=0)
        normalized_expected = [
            [*row, *([None] * (width - len(row)))] for row in expected_matrix
        ]
        return (
            actual_rows == normalized_expected
            and result.data.get("sheet") == expected_sheet
            and result.data.get("headers") == expected_headers
            and result.data.get("rows") == len(expected_rows)
        )
    finally:
        workbook.close()


async def verify_excel_created(
    arguments: ExcelCreateInput,
    result: ActionResult,
) -> bool:
    return await asyncio.to_thread(_verify_excel_result, arguments, result)


def create_excel_definition() -> ActionDefinition:
    return ActionDefinition(
        name="excel.create",
        description="Criar planilha Excel",
        input_model=ExcelCreateInput,
        handler=create_excel,
        verifier=verify_excel_created,
        risk=ActionRisk.WRITE_FILE,
        confirmation_required=False,
        timeout=30.0,
        desktop_exclusive=True,
        persistence=PersistencePolicy.SANITIZED,
        allowed_sources=frozenset({"chat", "api"}),
    )
