"""Read-only, fail-closed catalog of local PBIX-to-service references."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID


MAX_CATALOG_BYTES = 1024 * 1024
_CONNECTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_CATALOG_FIELDS = frozenset({"version", "reports"})
_REQUIRED_REPORT_FIELDS = frozenset({"local_file", "connection_id", "workspace_id", "report_id"})
_REPORT_FIELDS = _REQUIRED_REPORT_FIELDS | {"publish_to_web_src"}

CatalogStatus = Literal["found", "not_configured", "invalid"]
LookupStatus = Literal["found", "not_linked", "not_configured", "invalid"]


@dataclass(frozen=True, slots=True)
class ReportLink:
    local_file: str
    connection_id: str
    workspace_id: UUID
    report_id: UUID
    publish_to_web_src: str | None = None


@dataclass(frozen=True, slots=True)
class ReportCatalog:
    version: Literal[1]
    reports: tuple[ReportLink, ...]


@dataclass(frozen=True, slots=True)
class CatalogLoadResult:
    status: CatalogStatus
    catalog: ReportCatalog | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogLookupResult:
    status: LookupStatus
    link: ReportLink | None = None
    error_code: str | None = None


class _CatalogLocationUnavailable(ValueError):
    pass


class _InvalidCatalog(ValueError):
    pass


def resolve_catalog_path(local_app_data: str | os.PathLike[str] | None = None) -> Path:
    """Return the local catalog path without creating directories or files."""

    base = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA")
    if base is None or not str(base).strip():
        raise _CatalogLocationUnavailable
    return Path(base) / "ServicesBI_Jarvis" / "powerbi" / "reports.json"


def load_catalog(catalog_path: str | os.PathLike[str] | None = None) -> CatalogLoadResult:
    """Load and validate the entire catalog, returning only sanitized states."""

    try:
        path = Path(catalog_path) if catalog_path is not None else resolve_catalog_path()
    except (_CatalogLocationUnavailable, TypeError, ValueError):
        return CatalogLoadResult(
            status="not_configured", error_code="local_app_data_unavailable"
        )

    try:
        with path.open("rb") as catalog_file:
            payload = catalog_file.read(MAX_CATALOG_BYTES + 1)
    except FileNotFoundError:
        return CatalogLoadResult(status="not_configured", error_code="catalog_not_found")
    except OSError:
        return CatalogLoadResult(status="invalid", error_code="catalog_read_failed")

    if len(payload) > MAX_CATALOG_BYTES:
        return CatalogLoadResult(status="invalid", error_code="file_too_large")

    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return CatalogLoadResult(status="invalid", error_code="invalid_json")

    try:
        catalog = _parse_catalog(document)
    except _InvalidCatalog as exc:
        return CatalogLoadResult(status="invalid", error_code=str(exc))
    return CatalogLoadResult(status="found", catalog=catalog)


def find_report_link(
    local_file: str,
    catalog_path: str | os.PathLike[str] | None = None,
) -> CatalogLookupResult:
    """Find a validated report reference using a case-insensitive filename match."""

    if not _is_simple_pbix_filename(local_file):
        return CatalogLookupResult(status="invalid", error_code="invalid_lookup")

    loaded = load_catalog(catalog_path)
    if loaded.status != "found" or loaded.catalog is None:
        return CatalogLookupResult(
            status=loaded.status,
            error_code=loaded.error_code,
        )

    lookup_key = local_file.casefold()
    for report in loaded.catalog.reports:
        if report.local_file.casefold() == lookup_key:
            return CatalogLookupResult(status="found", link=report)
    return CatalogLookupResult(status="not_linked")


def _parse_catalog(document: object) -> ReportCatalog:
    if not isinstance(document, dict) or set(document) != _CATALOG_FIELDS:
        raise _InvalidCatalog("invalid_schema")
    if type(document["version"]) is not int or document["version"] != 1:
        raise _InvalidCatalog("invalid_schema")

    raw_reports = document["reports"]
    if not isinstance(raw_reports, list):
        raise _InvalidCatalog("invalid_schema")

    reports: list[ReportLink] = []
    seen_files: set[str] = set()
    for raw_report in raw_reports:
        report = _parse_report(raw_report)
        file_key = report.local_file.casefold()
        if file_key in seen_files:
            raise _InvalidCatalog("duplicate_local_file")
        seen_files.add(file_key)
        reports.append(report)
    return ReportCatalog(version=1, reports=tuple(reports))


def _parse_report(raw_report: object) -> ReportLink:
    if not isinstance(raw_report, dict) or not _REQUIRED_REPORT_FIELDS <= set(raw_report) <= _REPORT_FIELDS:
        raise _InvalidCatalog("invalid_schema")

    local_file = raw_report["local_file"]
    connection_id = raw_report["connection_id"]
    if not _is_simple_pbix_filename(local_file):
        raise _InvalidCatalog("invalid_schema")
    if not isinstance(connection_id, str) or not _CONNECTION_ID_PATTERN.fullmatch(
        connection_id
    ):
        raise _InvalidCatalog("invalid_schema")

    try:
        workspace_id = UUID(raw_report["workspace_id"])
        report_id = UUID(raw_report["report_id"])
    except (AttributeError, TypeError, ValueError):
        raise _InvalidCatalog("invalid_schema") from None

    publish_to_web_src = raw_report.get("publish_to_web_src")
    if publish_to_web_src is not None:
        from app.powerbi.browser import validate_publish_to_web_src
        try:
            publish_to_web_src = validate_publish_to_web_src(publish_to_web_src)
        except ValueError:
            raise _InvalidCatalog("invalid_schema") from None

    return ReportLink(
        local_file=local_file,
        connection_id=connection_id,
        workspace_id=workspace_id,
        report_id=report_id,
        publish_to_web_src=publish_to_web_src,
    )


def _is_simple_pbix_filename(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.casefold() == ".pbix" or not value.casefold().endswith(".pbix"):
        return False
    if ".." in value or any(character in value for character in ("/", "\\", ":")):
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    return Path(value).name == value
