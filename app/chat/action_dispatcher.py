"""Classificacao deterministica de pedidos executaveis do chat."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.actions.models import ActionRequest


EXCEL_PATTERN = re.compile(r"\b(planilha|excel|spreadsheet|xlsx)\b", re.I)
CREATE_PATTERN = re.compile(
    r"\b(cri[ae]|criar|gere|gerar|faça|faca|make|create|generate)\b",
    re.I,
)
WORD_PATTERN = re.compile(r"\b(word|docx)\b|\.docx\b", re.I)
FILENAME_PATTERN = re.compile(
    r"\bchamad[oa]\s+(?P<filename>.+?)"
    r"(?=\s+(?:com\s+o\s+conte[uú]do|com\s+o\s+texto|contendo|explicando)\b|$)",
    re.I,
)
EXPLICIT_CONTENT_PATTERN = re.compile(
    r"\b(?:com\s+o\s+conte[uú]do|com\s+o\s+texto)\s*:?\s*(?P<content>.+)$",
    re.I,
)
CONTAINING_PATTERN = re.compile(r"\bcontendo\s+(?P<content>.+)$", re.I)
ELABORATION_PATTERN = re.compile(r"\b(?P<instruction>explicando\s+.+)$", re.I)
EXCEL_COMMAND_PATTERN = re.compile(
    r"^\s*(?:jarvis[,:]?\s*)?(?:por\s+favor[,.]?\s*)?"
    r"(?:crie|criar|gere|gerar|faça|faca|make|create|generate)\b",
    re.I,
)
EXCEL_FILENAME_PATTERN = re.compile(
    r"\bchamad[oa]\s+(?P<filename>.+?\.xlsx)\s+com\s+os\s+dados\s*:",
    re.I,
)
EXCEL_DATA_PATTERN = re.compile(
    r"\bcom\s+os\s+dados\s*:\s*"
    r"cabe[cç]alhos\s*:\s*(?P<headers>.+?)\s*;\s*"
    r"linhas\s*:\s*(?P<rows>.+?)\s*$",
    re.I,
)
EXCEL_DRAFT_PATTERN = re.compile(
    r"\bchamad[oa]\s+(?P<filename>.+?\.xlsx)\s+"
    r"(?P<instruction>(?:com\s+uma\s+estrutura\b|estruturando\b|para\b).+)$",
    re.I,
)
APP_OPEN_PATTERN = re.compile(
    r"^\s*(?:jarvis[,:]?\s*)?"
    r"(?:abra|abre|abrir|inicie|inicia|iniciar|open|start)\s+"
    r"(?:o|a)?\s*"
    r"(?P<application>vs\s*code|vscode|word|excel|power\s*bi)"
    r"\s*(?:por\s+favor)?\s*[.!]?\s*$",
    re.I,
)
POWERBI_OPEN_PATTERNS = (
    re.compile(
        r"^\s*(?:jarvis[,:]?\s*)?(?:abra|abre|abrir|acesse|acessar|open)\s+"
        r"(?:o|a)\s+dashboard\s+(?P<name>.+?)\s*[.!]?\s*$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:jarvis[,:]?\s*)?(?:abra|abre|abrir|open)\s+"
        r"no\s+power\s*bi\s+(?P<name>.+?)\s*[.!]?\s*$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:jarvis[,:]?\s*)?(?:abra|abre|abrir|open)\s+"
        r"(?:o|a)\s+relat[oó]rio\s+power\s*bi\s+(?P<name>.+?)\s*[.!]?\s*$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:jarvis[,:]?\s*)?(?:abra|abre|abrir|open)\s+"
        r"(?P<name>dashboard\s+.+?)\s*[.!]?\s*$",
        re.I,
    ),
    re.compile(
        r"^\s*(?:jarvis[,:]?\s*)?(?:abra|abre|abrir|open)\s+"
        r"(?:(?:o|a)\s+)?(?:arquivo\s+)?(?P<name>.+?\.pbix)\s*[.!]?\s*$",
        re.I,
    ),
)
EXPLICIT_FILE_OPEN_PATTERN = re.compile(
    r"^\s*(?:jarvis[,:]?\s*)?"
    r"(?:abra|abre|abrir|open)\s+"
    r"(?:(?:o|a)\s+)?(?:arquivo|documento)\s+"
    r"(?P<name>.+?)\s*[.!]?\s*$",
    re.I,
)
EXTENSION_FILE_OPEN_PATTERN = re.compile(
    r"^\s*(?:jarvis[,:]?\s*)?"
    r"(?:abra|abre|abrir|open)\s+"
    r"(?:(?:o|a)\s+)?"
    r"(?P<name>.+?\.(?:docx|xlsx|xlsm|pbix))\s*[.!]?\s*$",
    re.I,
)
_INVALID_SHEET_CHARACTERS = re.compile(r"[\\/*?:\[\]]")

LimitedText = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=1000),
]
CellValue = LimitedText | StrictInt | StrictFloat | StrictBool | None


class ExcelGeneratedContent(BaseModel):
    """Contrato interno e fechado para a estrutura produzida pelo provider."""

    model_config = ConfigDict(extra="forbid")

    sheet: LimitedText
    headers: list[LimitedText] = Field(min_length=1, max_length=50)
    rows: list[list[CellValue]] = Field(max_length=1000)

    @field_validator("sheet")
    @classmethod
    def validate_sheet(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 31
            or _INVALID_SHEET_CHARACTERS.search(normalized)
        ):
            raise ValueError("Nome de worksheet invalido.")
        return normalized

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Headers nao podem ser vazios.")
        return normalized

    @model_validator(mode="after")
    def validate_row_width(self) -> "ExcelGeneratedContent":
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("Cada row deve ter a mesma quantidade de headers.")
        return self


@dataclass(frozen=True, slots=True)
class WordContentDraft:
    filename: str
    instruction: str

    @property
    def elaboration_prompt(self) -> str:
        return (
            "Elabore o conteúdo de um documento Word atendendo à instrução abaixo. "
            "Retorne somente o texto final do documento, sem explicar o processo e "
            "sem repetir a instrução literalmente.\n\n"
            f"Instrução: {self.instruction}"
        )

    def to_action_request(self, content: str) -> ActionRequest:
        return ActionRequest(
            action="word.create",
            arguments={"filename": self.filename, "content": content},
            source="chat",
        )


@dataclass(frozen=True, slots=True)
class ExcelContentDraft:
    filename: str
    instruction: str

    @property
    def elaboration_prompt(self) -> str:
        return (
            "Elabore uma estrutura de planilha Excel conforme a instrucao abaixo. "
            "Retorne somente JSON valido, sem Markdown, sem bloco de codigo, sem "
            "comentarios e sem texto antes ou depois. O objeto deve conter "
            "exclusivamente as propriedades sheet, headers e rows. sheet deve ser "
            "uma string valida; headers deve conter de 1 a 50 strings; rows deve "
            "conter no maximo 1000 listas, cada uma com exatamente a mesma "
            "quantidade de celulas dos headers. Use somente strings de ate 1000 "
            "caracteres, numeros, booleanos ou null nas celulas. Nao inclua "
            "filename, path, action, source, openFile, overwrite ou qualquer "
            "configuracao de seguranca.\n\n"
            f"Instrucao: {self.instruction}"
        )

    def to_action_request(self, content: str) -> ActionRequest:
        generated = ExcelGeneratedContent.model_validate_json(content)
        return ActionRequest(
            action="excel.create",
            arguments={
                "filename": self.filename,
                "sheet": generated.sheet,
                "headers": generated.headers,
                "rows": generated.rows,
                "openFile": False,
            },
            source="chat",
        )


@dataclass(frozen=True, slots=True)
class FileOpenIntent:
    name: str

def _word_filename(message: str) -> str | None:
    match = FILENAME_PATTERN.search(message)
    if match is None:
        return None
    filename = match.group("filename").strip().strip("\"'")
    if not filename:
        return None
    if not filename.lower().endswith(".docx"):
        filename += ".docx"
    return filename


def _explicit_word_content(message: str) -> str | None:
    for pattern in (EXPLICIT_CONTENT_PATTERN, CONTAINING_PATTERN):
        match = pattern.search(message)
        if match is not None:
            content = match.group("content").strip()
            return content or None
    return None


def _excel_scalar(value: str) -> str | int | float:
    normalized = value.strip()
    if re.fullmatch(r"[+-]?\d+", normalized):
        return int(normalized)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", normalized):
        return float(normalized)
    return normalized


def _excel_cells(value: str) -> list[str | int | float]:
    parsed = next(csv.reader([value], skipinitialspace=True))
    return [_excel_scalar(cell) for cell in parsed]


def _excel_request(message: str) -> ActionRequest | None:
    if EXCEL_COMMAND_PATTERN.search(message) is None:
        return None
    filename_match = EXCEL_FILENAME_PATTERN.search(message)
    data_match = EXCEL_DATA_PATTERN.search(message)
    if filename_match is None or data_match is None:
        return None
    filename = filename_match.group("filename").strip().strip("\"'")
    headers = _excel_cells(data_match.group("headers"))
    rows = [
        _excel_cells(row)
        for row in data_match.group("rows").split("|")
        if row.strip()
    ]
    if not filename or not headers or not rows:
        return None
    return ActionRequest(
        action="excel.create",
        arguments={"filename": filename, "headers": headers, "rows": rows},
        source="chat",
    )


def _excel_draft(message: str) -> ExcelContentDraft | None:
    if EXCEL_COMMAND_PATTERN.search(message) is None:
        return None
    if re.search(r"\bcom\s+os\s+dados\s*:", message, re.I):
        return None
    match = EXCEL_DRAFT_PATTERN.search(message)
    if match is None:
        return None
    filename = match.group("filename").strip().strip("\"'")
    instruction = match.group("instruction").strip()
    if not filename or not instruction:
        return None
    return ExcelContentDraft(filename=filename, instruction=instruction)


def _app_open_request(message: str) -> ActionRequest | None:
    match = APP_OPEN_PATTERN.fullmatch(message)
    if match is None:
        return None
    requested = re.sub(r"\s+", "", match.group("application")).casefold()
    application = {
        "vscode": "vscode",
        "word": "word",
        "excel": "excel",
        "powerbi": "powerbi",
    }[requested]
    return ActionRequest(
        action="app.open",
        arguments={"application": application},
        source="chat",
    )


def _powerbi_open_request(message: str) -> ActionRequest | None:
    for pattern in POWERBI_OPEN_PATTERNS:
        match = pattern.fullmatch(message)
        if match is None:
            continue
        name = match.group("name").strip().strip("\"'")
        if not name or re.search(
            r"\s+e\s+(?:(?:o|a)\s+)?(?:dashboard|relat[oó]rio|power\s*bi)\b",
            name,
            re.I,
        ):
            return None
        return ActionRequest(
            action="powerbi.open",
            arguments={"name": name},
            source="chat",
        )
    return None


def _file_open_intent(message: str) -> FileOpenIntent | None:
    for pattern in (EXPLICIT_FILE_OPEN_PATTERN, EXTENSION_FILE_OPEN_PATTERN):
        match = pattern.fullmatch(message)
        if match is None:
            continue
        name = match.group("name").strip().strip("\"'")
        if name:
            return FileOpenIntent(name=name)
    return None


class ActionDispatcher:
    def resolve(
        self, message: str
    ) -> ActionRequest | WordContentDraft | ExcelContentDraft | FileOpenIntent | None:
        app_request = _app_open_request(message)
        if app_request is not None:
            return app_request
        powerbi_request = _powerbi_open_request(message)
        if powerbi_request is not None:
            return powerbi_request
        file_intent = _file_open_intent(message)
        if file_intent is not None:
            return file_intent
        if not CREATE_PATTERN.search(message):
            return None

        is_excel = EXCEL_PATTERN.search(message) is not None
        is_word = WORD_PATTERN.search(message) is not None
        if is_excel and is_word:
            return None
        if is_excel:
            return _excel_request(message) or _excel_draft(message)
        if not is_word:
            return None

        filename = _word_filename(message)
        if filename is None:
            return None
        content = _explicit_word_content(message)
        if content is not None:
            return ActionRequest(
                action="word.create",
                arguments={"filename": filename, "content": content},
                source="chat",
            )
        elaboration = ELABORATION_PATTERN.search(message)
        if elaboration is not None:
            return WordContentDraft(
                filename=filename,
                instruction=elaboration.group("instruction").strip(),
            )
        return None
