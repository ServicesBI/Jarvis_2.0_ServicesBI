from __future__ import annotations

import asyncio
import importlib
import json
import tempfile
import unittest
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.actions.file_resolve import FileResolution
from app.actions.models import ActionRequest, ActionResult, ActionRisk, PersistencePolicy
from app.actions.registry import ActionNotAllowedError, DuplicateActionError
from app.chat.action_dispatcher import ActionDispatcher, FileOpenIntent
from app.chat.executor import ChatExecutor
from app.chat.models import ChatRequest
from app.chat.service import ChatService
from app.main import create_app
from app.powerbi.browser import BrowserOpenOutcome, BrowserOpenResult
from app.powerbi.catalog import CatalogLookupResult, ReportLink
from app.powerbi.desktop import PowerBIDesktopOpenResult, PowerBIDesktopStatus
from app.tasks import TaskManager


WORKSPACE_ID = UUID("2fc560a6-6146-4721-8a5f-d9f134a544fb")
REPORT_ID = UUID("7a42550d-ffee-43a8-a3cc-a7a71a9a44ff")


def module():
    try:
        return importlib.import_module("app.actions.powerbi_open")
    except ModuleNotFoundError as exc:
        raise AssertionError("app.actions.powerbi_open ainda não foi implementado") from exc


class PowerBIOpenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Power BI"
        self.root.mkdir()
        self.pbix = self.root / "Dashboard Financeiro.pbix"
        self.pbix.write_bytes(b"PBIX")
        self.events: list[str] = []
        self.browser_calls: list[tuple[UUID, UUID]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def definition(
        self,
        *,
        file_status: str = "found",
        catalog_status: str = "found",
        browser_outcome: BrowserOpenOutcome = BrowserOpenOutcome.OPENED,
        publish_to_web_src: str | None = None,
        publish_outcome: BrowserOpenOutcome = BrowserOpenOutcome.OPENED,
        launch_error: bool = False,
        snapshots: tuple[set[int], ...] = ({41}, {41}),
    ):
        def resolve_file(name: str, **_kwargs):
            self.events.append(f"resolve:{name}")
            if file_status == "found":
                return FileResolution(status="found", filename=self.pbix.name, path=self.pbix.name, extension=".pbix")
            if file_status == "ambiguous":
                return FileResolution(status="ambiguous", candidates=["A.pbix", "a.PBIX"])
            return FileResolution(status="not_found")

        def catalog(filename: str):
            self.events.append(f"catalog:{filename}")
            if catalog_status == "found":
                return CatalogLookupResult(status="found", link=ReportLink(filename, "connection", WORKSPACE_ID, REPORT_ID, publish_to_web_src))
            return CatalogLookupResult(status=catalog_status)

        async def desktop(file_path: Path):
            self.events.append(f"desktop:{file_path}")
            opened = not launch_error and any(snapshots)
            return PowerBIDesktopOpenResult(
                status=PowerBIDesktopStatus.OPENED if opened else PowerBIDesktopStatus.FAILED,
                launch_requested=True,
                process_detected=opened,
                report_loaded=opened,
                error_code=None if opened else "report_not_loaded",
            )

        def browser(workspace_id: UUID, report_id: UUID):
            self.events.append("browser")
            self.browser_calls.append((workspace_id, report_id))
            return BrowserOpenResult(
                outcome=browser_outcome,
                launch_requested=browser_outcome is BrowserOpenOutcome.OPENED,
                process_detected=browser_outcome is BrowserOpenOutcome.OPENED,
            )

        def publish(source: str):
            self.events.append(f"publish:{source}")
            return BrowserOpenResult(outcome=publish_outcome, launch_requested=publish_outcome is BrowserOpenOutcome.OPENED)

        return module().create_powerbi_open_definition(
            powerbi_workspace=self.root,
            file_resolver=resolve_file,
            catalog_lookup=catalog,
            browser_opener=browser,
            publish_opener=publish,
            desktop_opener=desktop,
        )

    def run_handler(self, definition, name="Dashboard Financeiro"):
        arguments = definition.input_model.model_validate({"name": name})
        return asyncio.run(definition.handler(arguments))

    def test_schema_is_closed_and_normalizes_only_safe_powerbi_names(self) -> None:
        model = module().PowerBIOpenInput
        expected = {
            "Dashboard Financeiro": "Dashboard Financeiro.pbix",
            "Dashboard Financeiro.pbix": "Dashboard Financeiro.pbix",
            "Dashboard Financeiro.PBIX": "Dashboard Financeiro.PBIX",
            "Dashboard Financeiro v1.2": "Dashboard Financeiro v1.2.pbix",
        }
        for raw, normalized in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(model(name=raw).name, normalized)
        for raw in (
            "Planilha.xlsx", "Documento.docx", "Macro.xlsm", "../x", r"C:\x.pbix",
            r"\\server\share\x.pbix", r"\\?\C:\x.pbix", "dir/x.pbix", r"dir\x.pbix",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    model(name=raw)
        with self.assertRaises(ValidationError):
            model.model_validate({"name": "x", "url": "https://evil.example"})

    def test_definition_has_approved_isolated_contract(self) -> None:
        definition = self.definition()
        self.assertEqual(definition.name, "powerbi.open")
        self.assertEqual(definition.risk, ActionRisk.EXTERNAL)
        self.assertFalse(definition.confirmation_required)
        self.assertTrue(definition.desktop_exclusive)
        self.assertEqual(definition.allowed_sources, frozenset({"chat", "api"}))
        self.assertEqual(definition.persistence, PersistencePolicy.SANITIZED)
        self.assertTrue(definition.requires_verification)
        self.assertEqual(definition.timeout, 90.0)

    def test_explicit_pbix_resolution_ignores_excel_with_same_stem(self) -> None:
        excel = Path(self.temp.name) / "Excel"
        excel.mkdir()
        (excel / "Dashboard Financeiro.xlsx").write_bytes(b"xlsx")
        result = self.run_handler(self.definition(catalog_status="not_linked"))
        self.assertEqual(result.data["filename"], self.pbix.name)
        self.assertEqual(self.events[0], "resolve:Dashboard Financeiro.pbix")

    def test_not_found_and_ambiguous_have_no_effects(self) -> None:
        for status in ("not_found", "ambiguous"):
            with self.subTest(status=status):
                self.events.clear()
                result = self.run_handler(self.definition(file_status=status))
                self.assertEqual(result.data["outcome"], status)
                self.assertFalse(any(event in {"desktop_launch", "browser"} for event in self.events))

    def test_found_opens_browser_only_after_desktop_process_is_detected(self) -> None:
        result = self.run_handler(self.definition(snapshots=(set(), {55})))
        self.assertEqual(result.data["outcome"], "partial")
        self.assertEqual(self.browser_calls, [(WORKSPACE_ID, REPORT_ID)])
        desktop_event = f"desktop:{self.pbix.resolve()}"
        self.assertIn(desktop_event, self.events)
        self.assertLess(self.events.index(desktop_event), self.events.index("browser"))

    def test_publish_runs_after_service_and_preserves_exact_source(self) -> None:
        source = "https://app.powerbi.com/view?r=Exact%2BToken%3D&keep=1"
        result = self.run_handler(self.definition(publish_to_web_src=source))
        desktop = f"desktop:{self.pbix.resolve()}"
        self.assertLess(self.events.index(desktop), self.events.index("browser"))
        self.assertLess(self.events.index("browser"), self.events.index(f"publish:{source}"))
        self.assertEqual(result.data["stages"]["desktop"]["status"], "opened")
        self.assertEqual(result.data["stages"]["service"]["status"], "opened")
        self.assertEqual(result.data["stages"]["publish_to_web"]["status"], "opened")

    def test_publish_failure_is_not_full_success(self) -> None:
        result = self.run_handler(self.definition(
            publish_to_web_src="https://app.powerbi.com/view?r=Exact",
            publish_outcome=BrowserOpenOutcome.LAUNCH_FAILED,
        ))
        self.assertFalse(result.ok)
        self.assertEqual(result.data["stages"]["publish_to_web"]["status"], "failed")

    def test_real_x_meta_without_publish_is_failed_not_partial_success(self) -> None:
        self.pbix = self.root / "Real X Meta (Recomendações).pbix"
        self.pbix.write_bytes(b"PBIX")
        result = self.run_handler(self.definition(publish_to_web_src=None), "Real X Meta (Recomendações)")
        self.assertFalse(result.ok)
        self.assertEqual(result.data["outcome"], "failed")
        self.assertEqual(result.data["stages"]["publish_to_web"]["status"], "not_configured")

    def test_controlled_real_x_metas_alias_normalizes_to_catalogued_filename(self) -> None:
        value = module().PowerBIOpenInput(name="Real x Metas (Recomendações)")
        self.assertEqual(value.name, "Real X Meta (Recomendações).pbix")

    def test_desktop_opener_receives_exact_validated_pbix(self) -> None:
        self.run_handler(self.definition(catalog_status="not_linked"))

        self.assertIn(f"desktop:{self.pbix.resolve()}", self.events)

    def test_preexisting_process_is_valid_only_after_launch_is_accepted(self) -> None:
        result = self.run_handler(self.definition(snapshots=({41},)))
        self.assertEqual(result.data["outcome"], "partial")
        self.events.clear()
        self.browser_calls.clear()
        failed = self.run_handler(self.definition(launch_error=True, snapshots=({41},)))
        self.assertEqual(failed.data["outcome"], "failed")
        self.assertNotIn("browser", self.events)
        self.assertEqual(self.browser_calls, [])

    def test_process_timeout_fails_without_browser(self) -> None:
        result = self.run_handler(self.definition(snapshots=(set(), set())))
        self.assertEqual(result.data["outcome"], "failed")
        self.assertFalse(result.ok)
        self.assertFalse(result.data["desktop_opened"])
        self.assertEqual(self.browser_calls, [])

    def test_desktop_failure_marks_task_failed_instead_of_completed(self) -> None:
        definition = self.definition(launch_error=True)
        registry = self.application_registry(definition)
        manager = TaskManager(Path(self.temp.name) / "semantic-tasks.json")
        from app.actions.engine import ActionEngine

        async def execute():
            task = ActionEngine(registry, manager).submit(
                ActionRequest(
                    action="powerbi.open",
                    arguments={"name": "Dashboard Financeiro"},
                    source="chat",
                )
            )
            return await manager.wait(task["task_id"])

        finished = asyncio.run(execute())

        self.assertEqual(finished["status"], "failed")
        self.assertIsNone(finished["result"])

    @staticmethod
    def application_registry(definition):
        from app.actions.registry import ActionRegistry

        registry = ActionRegistry()
        registry.register(definition)
        return registry

    def test_catalog_nonfound_states_are_desktop_only_partial(self) -> None:
        for status in ("not_linked", "not_configured", "invalid"):
            with self.subTest(status=status):
                self.browser_calls.clear()
                result = self.run_handler(self.definition(catalog_status=status))
                self.assertEqual(result.data["outcome"], "failed")
                self.assertFalse(result.ok)
                self.assertEqual(result.data["online_link_status"], status)
                self.assertTrue(result.data["desktop_opened"])
                self.assertFalse(result.data["browser_opened"])
                self.assertEqual(result.data.get("publish_to_web_status"), "not_configured")
                self.assertEqual(self.browser_calls, [])

    def test_browser_outcomes_map_to_full_or_partial(self) -> None:
        for browser_outcome in BrowserOpenOutcome:
            with self.subTest(browser_outcome=browser_outcome):
                result = self.run_handler(self.definition(browser_outcome=browser_outcome))
                expected = "partial" if browser_outcome is BrowserOpenOutcome.OPENED else "failed"
                self.assertEqual(result.data["outcome"], expected)
                self.assertEqual(result.data["browser_opened"], expected == "partial")
                self.assertEqual(result.ok, expected == "partial")
                self.assertEqual(result.data.get("publish_to_web_status"), "not_configured")

    def test_result_is_sanitized_and_summary_never_claims_page_loaded(self) -> None:
        result = self.run_handler(self.definition())
        serialized = json.dumps(result.model_dump(mode="json"))
        for forbidden in (str(self.root), "https://", str(WORKSPACE_ID), str(REPORT_ID), "connection", "token", "credential", "stack"):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("carregado", (result.summary or "").casefold())

    def test_verifier_enforces_desktop_and_composite_consistency(self) -> None:
        definition = self.definition(snapshots=({41}, {41}))
        result = self.run_handler(definition)
        args = definition.input_model(name="Dashboard Financeiro")
        self.assertTrue(asyncio.run(definition.verifier(args, result)))

        without_desktop = result.model_copy(deep=True)
        without_desktop.data["desktop_opened"] = False
        self.assertFalse(asyncio.run(definition.verifier(args, without_desktop)))
        without_browser = result.model_copy(deep=True)
        without_browser.data["browser_opened"] = False
        self.assertFalse(asyncio.run(definition.verifier(args, without_browser)))


class PowerBIOfficialRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.manager = TaskManager(Path(self.temp.name) / "tasks.json")
        self.application = create_app(task_manager=self.manager)

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.temp.cleanup()

    def test_official_registry_resolves_powerbi_open_exactly_once(self) -> None:
        registry = self.application.state.action_registry
        for source in ("chat", "api"):
            with self.subTest(source=source):
                definitions = registry.definitions_for(source)
                matches = [item for item in definitions if item.name == "powerbi.open"]
                self.assertEqual(len(matches), 1)
                self.assertIs(registry.resolve("powerbi.open", source=source), matches[0])

    def test_action_engine_uses_the_official_registry_instance(self) -> None:
        self.assertIs(
            self.application.state.action_engine.registry,
            self.application.state.action_registry,
        )

    def test_existing_actions_remain_resolvable_from_official_registry(self) -> None:
        registry = self.application.state.action_registry
        expected = {
            "app.open",
            "file.open",
            "file.resolve",
            "excel.create",
            "word.create",
            "powerbi.open",
        }
        resolved = {registry.resolve(name, source="api").name for name in expected}
        self.assertEqual(resolved, expected)

    def test_official_registry_rejects_duplicate_powerbi_open(self) -> None:
        registry = self.application.state.action_registry
        with self.assertRaises(DuplicateActionError):
            registry.register(module().create_powerbi_open_definition())

    def _install_effect_free_definition(self) -> None:
        registry = self.application.state.action_registry
        definition = registry.resolve("powerbi.open", source="api")

        async def handler(_arguments):
            return ActionResult(
                ok=True,
                action="powerbi.open",
                summary="Execucao controlada de teste.",
                data={"outcome": "controlled"},
            )

        async def verifier(_arguments, result):
            return result.data.get("outcome") == "controlled"

        registry._definitions["powerbi.open"] = replace(
            definition,
            handler=handler,
            verifier=verifier,
        )

    async def _submit_without_external_effects(self, source: str) -> dict[str, object]:
        self._install_effect_free_definition()
        submitted = self.application.state.action_engine.submit(
            ActionRequest(
                action="powerbi.open",
                arguments={"name": "Dashboard Financeiro"},
                source=source,
            )
        )
        return await self.manager.wait(submitted["task_id"])

    async def test_chat_source_passes_registry_policy_and_engine(self) -> None:
        finished = await self._submit_without_external_effects("chat")
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["type"], "powerbi.open")

    async def test_api_source_passes_registry_policy_and_engine(self) -> None:
        finished = await self._submit_without_external_effects("api")
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["type"], "powerbi.open")

    def test_voice_source_is_rejected_before_task_creation(self) -> None:
        before = self.manager.list()
        with self.assertRaises(ActionNotAllowedError):
            self.application.state.action_engine.submit(
                ActionRequest(
                    action="powerbi.open",
                    arguments={"name": "Dashboard Financeiro"},
                    source="voice",
                )
            )
        self.assertEqual(self.manager.list(), before)


class RecordingChatExecutor(ChatExecutor):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        yield "provider fallback"


class PowerBITextDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = ActionDispatcher()

    def assert_powerbi_request(self, message: str, name: str) -> None:
        self.assertEqual(
            self.dispatcher.resolve(message),
            ActionRequest(action="powerbi.open", arguments={"name": name}, source="chat"),
        )

    def test_known_applications_keep_app_open_priority(self) -> None:
        cases = {"Abra o Power BI": "powerbi", "Abra o Word": "word", "Abra o Excel": "excel", "Abra o VS Code": "vscode"}
        for message, application in cases.items():
            with self.subTest(message=message):
                self.assertEqual(self.dispatcher.resolve(message), ActionRequest(action="app.open", arguments={"application": application}, source="chat"))

    def test_bounded_powerbi_vocabulary_extracts_only_the_name(self) -> None:
        cases = {
            "Abra Dashboard Financeiro": "Dashboard Financeiro",
            "Abra o dashboard Financeiro": "Financeiro",
            "Abra o dashboard Dashboard Financeiro": "Dashboard Financeiro",
            "Abra no Power BI Dashboard Financeiro": "Dashboard Financeiro",
            "Abra o relatório Power BI Financeiro": "Financeiro",
        }
        for message, name in cases.items():
            with self.subTest(message=message):
                self.assert_powerbi_request(message, name)

    def test_open_and_access_real_x_metas_use_the_same_powerbi_action(self) -> None:
        expected = ActionRequest(
            action="powerbi.open",
            arguments={"name": "Real x Metas (Recomendações)"},
            source="chat",
        )
        self.assertEqual(self.dispatcher.resolve("Jarvis, abra o Dashboard Real x Metas (Recomendações)"), expected)
        self.assertEqual(self.dispatcher.resolve("Jarvis, acesse o Dashboard Real x Metas (Recomendações)"), expected)

    def test_pbix_extension_precedes_generic_file_flow_and_preserves_case(self) -> None:
        cases = {
            "Abra Dashboard Financeiro.pbix": "Dashboard Financeiro.pbix",
            "Abra Dashboard Financeiro.PBIX": "Dashboard Financeiro.PBIX",
            "Abra o arquivo Dashboard Financeiro.pbix": "Dashboard Financeiro.pbix",
        }
        for message, name in cases.items():
            with self.subTest(message=message):
                self.assert_powerbi_request(message, name)

    def test_non_powerbi_file_commands_remain_generic(self) -> None:
        cases = {"Abra o arquivo Dashboard Financeiro": "Dashboard Financeiro", "Abra Relatorio.docx": "Relatorio.docx", "Abra Planilha.xlsx": "Planilha.xlsx", "Abra Modelo.xlsm": "Modelo.xlsm"}
        for message, name in cases.items():
            with self.subTest(message=message):
                intent = self.dispatcher.resolve(message)
                self.assertIsInstance(intent, FileOpenIntent)
                self.assertEqual(intent.name, name)

    def test_generic_empty_and_ambiguous_phrases_never_become_powerbi(self) -> None:
        messages = ("Abra Relatório Financeiro", "Abra meu painel financeiro", "Abra as configurações", "Abra uma nova planilha", "Abra o dashboard", "Abra no Power BI", "Dashboard Financeiro", "Abra", "Abra Dashboard Financeiro e Relatório Comercial")
        for message in messages:
            with self.subTest(message=message):
                resolution = self.dispatcher.resolve(message)
                self.assertFalse(isinstance(resolution, ActionRequest) and resolution.action == "powerbi.open")


class PowerBITextChatIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.manager = TaskManager(Path(self.temp.name) / "tasks.json")
        self.provider = RecordingChatExecutor()
        self.application = create_app(ChatService(self.provider), task_manager=self.manager)
        self.result = ActionResult(ok=True, action="powerbi.open", summary="Resultado Power BI controlado.", data={"outcome": "full_success"})
        registry = self.application.state.action_registry
        definition = registry.resolve("powerbi.open", source="chat")

        async def handler(_arguments):
            return self.result

        async def verifier(_arguments, _result):
            return True

        registry._definitions["powerbi.open"] = replace(definition, handler=handler, verifier=verifier)
        self.client = TestClient(self.application)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self, message: str = "Abra Dashboard Financeiro"):
        return self.client.post("/api/chat", json={"message": message})

    def test_action_summaries_reach_chat_for_every_powerbi_outcome(self) -> None:
        summaries = {
            "full_success": "Abri Dashboard Financeiro.pbix no Power BI Desktop e solicitei a abertura do relatório online no Chrome.",
            "partial": "Abri Dashboard Financeiro.pbix no Power BI Desktop, mas não há relatório online vinculado.",
            "not_found": "PBIX solicitado não encontrado.",
            "ambiguous": "PBIX solicitado possui correspondência ambígua.",
        }
        for outcome, summary in summaries.items():
            with self.subTest(outcome=outcome):
                self.result = ActionResult(ok=True, action="powerbi.open", summary=summary, data={"outcome": outcome})
                response = self.post()
                self.assertEqual(response.status_code, 200)
                self.assertIn(f"[system] {summary}", response.text)
        self.assertEqual(self.provider.requests, [])

    def test_failed_powerbi_action_never_falls_back_to_provider(self) -> None:
        self.result = ActionResult(ok=False, action="powerbi.open", summary="Summary não persistido em falha.", error="Falha Power BI controlada.", data={"outcome": "failed"})
        response = self.post()
        self.assertIn("[error]", response.text)
        self.assertIn("Falha Power BI controlada.", response.text)
        self.assertEqual(self.provider.requests, [])

    def test_summary_streaming_is_generic_for_non_powerbi_action(self) -> None:
        registry = self.application.state.action_registry
        definition = registry.resolve("app.open", source="chat")

        async def handler(_arguments):
            return ActionResult(ok=True, action="app.open", summary="Aplicativo controlado aberto.", data={"application": "word"})

        async def verifier(_arguments, _result):
            return True

        registry._definitions["app.open"] = replace(definition, handler=handler, verifier=verifier)
        response = self.post("Abra o Word")
        self.assertIn("[system] Aplicativo controlado aberto.", response.text)
        self.assertEqual(self.provider.requests, [])


if __name__ == "__main__":
    unittest.main()
