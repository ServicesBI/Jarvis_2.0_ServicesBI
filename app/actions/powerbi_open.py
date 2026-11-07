"""Action bounded: confirma Desktop e entao abre destinos Power BI cadastrados."""
from __future__ import annotations
from collections.abc import Awaitable, Callable
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.actions.file_open import EXTENSION_MEDIA_TYPES, validate_file_path
from app.actions.file_resolve import FileResolution, FileResolveInput, resolve_file_name
from app.actions.models import ActionArtifact, ActionResult, ActionRisk, PersistencePolicy
from app.actions.registry import ActionDefinition
from app.core.config import POWERBI_WORKSPACE
from app.powerbi.browser import BrowserOpenOutcome, BrowserOpenResult, open_powerbi_publish_to_web, open_powerbi_report
from app.powerbi.catalog import CatalogLookupResult, find_report_link
from app.powerbi.desktop import PowerBIDesktopOpenResult, open_powerbi_desktop

class PowerBIOpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = FileResolveInput(name=value).name
        suffix = Path(name).suffix.casefold()
        if suffix in {".docx", ".xlsx", ".xlsm"}:
            raise ValueError("Extensao gerenciada nao permitida para powerbi.open.")
        bare_name = name[:-5] if name.casefold().endswith(".pbix") else name
        if bare_name.casefold() == "real x metas (recomendações)".casefold():
            return "Real X Meta (Recomendações).pbix"
        return name if name.casefold().endswith(".pbix") else f"{name}.pbix"

FileResolver = Callable[..., FileResolution]
CatalogLookup = Callable[[str], CatalogLookupResult]
BrowserOpener = Callable[..., BrowserOpenResult]
PublishOpener = Callable[[str], BrowserOpenResult]
DesktopOpener = Callable[[Path], Awaitable[PowerBIDesktopOpenResult]]

def _data(*, filename: str | None, outcome: str, desktop_opened: bool,
          online_link_status: str | None, browser_opened: bool,
          browser_outcome: str | None, desktop_status: str = "failed",
          service_status: str = "not_configured", publish_status: str = "not_configured") -> dict[str, object]:
    return {"filename": filename, "outcome": outcome, "desktop_opened": desktop_opened,
        "online_link_status": online_link_status, "browser_opened": browser_opened,
        "browser_outcome": browser_outcome, "desktop_status": desktop_status,
        "service_status": service_status, "publish_to_web_status": publish_status,
        "stages": {"desktop": {"status": desktop_status}, "service": {"status": service_status},
                   "publish_to_web": {"status": publish_status}}}

def create_powerbi_open_definition(*, powerbi_workspace: Path | None = None,
    file_resolver: FileResolver = resolve_file_name, catalog_lookup: CatalogLookup = find_report_link,
    browser_opener: BrowserOpener = open_powerbi_report,
    publish_opener: PublishOpener = open_powerbi_publish_to_web,
    desktop_opener: DesktopOpener = open_powerbi_desktop) -> ActionDefinition:
    root = Path(powerbi_workspace or POWERBI_WORKSPACE).resolve()
    pending: dict[str, tuple[Path, str]] = {}

    async def handler(arguments: PowerBIOpenInput) -> ActionResult:
        try:
            resolution = file_resolver(arguments.name, powerbi_workspace=root)
        except (OSError, ValueError):
            resolution = FileResolution(status="not_found")
        if resolution.status != "found" or not resolution.filename:
            outcome = "ambiguous" if resolution.status == "ambiguous" else "not_found"
            return ActionResult(ok=False, action="powerbi.open", error=f"PBIX com resultado {outcome}.",
                data=_data(filename=None, outcome=outcome, desktop_opened=False, online_link_status=None, browser_opened=False, browser_outcome=None))
        filename = resolution.filename
        try:
            catalog = catalog_lookup(filename)
        except (OSError, ValueError):
            catalog = CatalogLookupResult(status="invalid", error_code="catalog_lookup_failed")
        try:
            file_path = validate_file_path(filename, powerbi_workspace=root)
        except (OSError, ValueError):
            return ActionResult(ok=False, action="powerbi.open", error=f"Nao foi possivel validar {filename}.",
                data=_data(filename=filename, outcome="failed", desktop_opened=False, online_link_status=catalog.status, browser_opened=False, browser_outcome=None))
        desktop = await desktop_opener(file_path)
        desktop_status = desktop.status.value
        if not desktop.opened or not desktop.report_loaded:
            return ActionResult(ok=False, action="powerbi.open", error=f"Nao foi possivel confirmar o carregamento de {filename} no Power BI Desktop.",
                data={**_data(filename=filename, outcome="failed", desktop_opened=False, online_link_status=catalog.status,
                    browser_opened=False, browser_outcome=None, desktop_status="failed"), "desktop_error": desktop.error_code})
        if catalog.status != "found" or catalog.link is None:
            return ActionResult(ok=False, action="powerbi.open", error=f"O PBIX {filename} foi carregado, mas nao possui vinculo online valido.",
                data=_data(filename=filename, outcome="failed", desktop_opened=True, online_link_status=catalog.status,
                    browser_opened=False, browser_outcome=None, desktop_status=desktop_status, service_status=catalog.status))
        service = browser_opener(catalog.link.workspace_id, catalog.link.report_id)
        service_opened = service.outcome is BrowserOpenOutcome.OPENED
        if not service_opened:
            return ActionResult(ok=False, action="powerbi.open", error=f"O PBIX {filename} foi carregado, mas o Power BI Service falhou.",
                data=_data(filename=filename, outcome="failed", desktop_opened=True, online_link_status=catalog.status,
                    browser_opened=False, browser_outcome=service.outcome.value, desktop_status=desktop_status, service_status="failed"))
        publish_status = "not_configured"
        if catalog.link.publish_to_web_src is not None:
            publish = publish_opener(catalog.link.publish_to_web_src)
            publish_status = "opened" if publish.outcome is BrowserOpenOutcome.OPENED else "failed"
        publish_required = filename.casefold() == "Real X Meta (Recomendações).pbix".casefold()
        outcome = "full" if publish_status == "opened" else "partial"
        data = _data(filename=filename, outcome=outcome, desktop_opened=True, online_link_status="found",
            browser_opened=True, browser_outcome=service.outcome.value, desktop_status=desktop_status,
            service_status="opened", publish_status=publish_status)
        if publish_status == "failed":
            return ActionResult(ok=False, action="powerbi.open", error="Power BI Publish to Web falhou.", data={**data, "outcome": "failed"})
        if publish_required and publish_status != "opened":
            return ActionResult(ok=False, action="powerbi.open", error="Publish to Web obrigatorio nao configurado.", data={**data, "outcome": "failed"})
        pending[arguments.name] = (file_path, outcome)
        publish_text = " e Publish to Web" if publish_status == "opened" else "; Publish to Web nao configurado"
        return ActionResult(ok=True, action="powerbi.open",
            summary=f"Confirmei {filename} no Power BI Desktop e solicitei o Power BI Service{publish_text}.",
            artifacts=[ActionArtifact(path=filename, exists=True, size=file_path.stat().st_size, media_type=EXTENSION_MEDIA_TYPES[".pbix"])], data=data)

    async def verifier(arguments: PowerBIOpenInput, result: ActionResult) -> bool:
        state = pending.pop(arguments.name, None)
        if state is None:
            return False
        file_path, outcome = state
        try:
            current = validate_file_path(file_path, powerbi_workspace=root)
        except (OSError, ValueError):
            return False
        stages = result.data.get("stages", {})
        return current == file_path and result.data.get("outcome") == outcome and result.data.get("desktop_opened") is True and result.data.get("browser_opened") is True and stages.get("desktop", {}).get("status") in {"opened", "already_open"} and stages.get("service", {}).get("status") == "opened" and stages.get("publish_to_web", {}).get("status") in {"opened", "not_configured"}

    return ActionDefinition(name="powerbi.open", description="Abrir PBIX autorizado e vinculos Power BI cadastrados",
        input_model=PowerBIOpenInput, handler=handler, verifier=verifier, risk=ActionRisk.EXTERNAL,
        confirmation_required=False, timeout=90.0, desktop_exclusive=True,
        persistence=PersistencePolicy.SANITIZED, allowed_sources=frozenset({"chat", "api"}))
