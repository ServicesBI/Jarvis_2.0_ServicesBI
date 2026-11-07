"""Operações reais de workbook usadas pelas automações do Jarvis."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from openpyxl import Workbook, load_workbook

from app.actions.policy import PathAccess, PathPolicy
from app.core.config import EXCEL_WORKSPACE, PROJECT_ROOT


PROJECTS_DIR = EXCEL_WORKSPACE.resolve()
DEFAULT_HEADERS = ["Produto", "Quantidade", "Valor Unitario", "Total"]
DEFAULT_ROWS = [
    ["Produto A", 2, 15.5],
    ["Produto B", 3, 22.0],
    ["Produto C", 1, 49.9],
]
_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_output_path(filename: str) -> Path:
    raw_name = filename.strip()
    candidate = Path(raw_name)
    windows_candidate = PureWindowsPath(raw_name)
    if not raw_name:
        raise ValueError("Nome do arquivo Excel e obrigatorio.")
    if candidate.is_absolute() or windows_candidate.is_absolute():
        raise ValueError("O nome do arquivo Excel nao pode ser um caminho absoluto.")
    if "/" in raw_name or "\\" in raw_name:
        raise ValueError("O nome do arquivo Excel nao pode conter diretorios.")
    if ".." in raw_name:
        raise ValueError("O nome do arquivo Excel nao pode conter '..'.")
    if candidate.name != raw_name or windows_candidate.name != raw_name:
        raise ValueError("Somente um nome simples de arquivo Excel e permitido.")
    if candidate.suffix.lower() != ".xlsx":
        raise ValueError("A extensao .xlsx e obrigatoria.")
    if _INVALID_FILENAME_CHARACTERS.search(raw_name) or raw_name.rstrip(". ") != raw_name:
        raise ValueError("Nome de arquivo Excel invalido.")

    projects_root = PROJECTS_DIR.resolve()
    path_policy = PathPolicy(write_roots=(projects_root,))
    return path_policy.validate(projects_root / raw_name, access=PathAccess.WRITE)


def expected_workbook_content(
    payload: dict[str, Any],
) -> tuple[str, list[Any], list[list[Any]]]:
    headers = list(
        DEFAULT_HEADERS if payload.get("headers") is None else payload["headers"]
    )
    raw_rows = DEFAULT_ROWS if payload.get("rows") is None else payload["rows"]
    rows: list[list[Any]] = []
    for index, row in enumerate(raw_rows, start=2):
        values = list(row) if isinstance(row, (list, tuple)) else [row]
        if len(headers) >= 4 and len(values) < 4:
            values.extend([None] * (3 - len(values)))
            values.append(f"=B{index}*C{index}")
        rows.append(values)
    sheet_name = str(payload.get("sheet") or "Dados")[:31]
    return sheet_name, headers, rows


def _safe_existing_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    allowed = (PROJECT_ROOT.resolve(), Path.home().resolve())
    if not any(path == root or root in path.parents for root in allowed):
        raise PermissionError("Caminho fora das areas autorizadas.")
    if not path.is_file():
        raise FileNotFoundError("Arquivo nao encontrado.")
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Somente arquivos .xlsx sao aceitos.")
    return path


def _create_workbook(payload: dict[str, Any]) -> dict[str, Any]:
    path = _safe_output_path(str(payload.get("filename") or "Planilha Jarvis.xlsx"))
    if path.exists():
        raise FileExistsError(f"Arquivo Excel ja existe: {path.name}")
    sheet_name, headers, rows = expected_workbook_content(payload)
    if not isinstance(headers, list) or not headers or len(headers) > 50:
        raise ValueError("Cabecalhos invalidos.")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Linhas invalidas.")

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    path = PathPolicy(write_roots=(PROJECTS_DIR.resolve(),)).validate(
        path,
        access=PathAccess.WRITE,
    )
    workbook.save(path)

    verified = load_workbook(path, data_only=False)
    verified_sheet = verified[verified.sheetnames[0]]
    formulas = [
        cell.value
        for row in verified_sheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str) and cell.value.startswith("=")
    ]
    result = {
        "ok": path.is_file() and path.stat().st_size > 0,
        "path": str(path),
        "size": path.stat().st_size,
        "sheet": verified_sheet.title,
        "headers": [cell.value for cell in verified_sheet[1]],
        "rows": max(0, verified_sheet.max_row - 1),
        "formulas": formulas,
        "opened": False,
    }
    verified.close()
    if payload.get("openFile") is True:
        os.startfile(path)
        result["opened"] = True
    return result


async def create_workbook(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_workbook, payload)


def _read_workbook(raw_path: str, sheet_name: str | None = None, *, formulas: bool = False) -> dict[str, Any]:
    path = _safe_existing_path(raw_path)
    workbook = load_workbook(path, data_only=not formulas, read_only=True)
    if sheet_name and sheet_name not in workbook.sheetnames:
        workbook.close()
        raise ValueError("Planilha nao encontrada no workbook.")
    sheet = workbook[sheet_name or workbook.sheetnames[0]]
    rows = [list(row) for row in sheet.iter_rows(values_only=True)]
    result = {"ok": True, "path": str(path), "sheet": sheet.title, "sheets": workbook.sheetnames, "rows": rows}
    workbook.close()
    return result


async def read_workbook(raw_path: str, sheet_name: str | None = None, *, formulas: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(_read_workbook, raw_path, sheet_name, formulas=formulas)
