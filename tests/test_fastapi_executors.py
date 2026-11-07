"""Caracterização da fundação de executores do PASSO 0D."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.executors.availability import ProviderAvailabilityService
from app.executors.cli import (
    AsyncCliExecutor,
    CliTimeoutError,
    CliUnavailableError,
)
from app.executors.service import (
    ExecutorService,
    codex_subprocess_environment,
    executor_service,
)
from app.main import create_app
from app.tasks.manager import TaskManager


def _isolated_task_manager(temp_dir: str) -> TaskManager:
    """create_app() sem task_manager= constroi um TaskManager real ligado a
    system/task-state.json (le/reconcilia esse arquivo no __init__), mesmo
    quando nenhum teste chama /api/tasks. Todo create_app() destes testes
    recebe um TaskManager isolado por esse motivo."""

    return TaskManager(Path(temp_dir) / "task-state.json")


VALID_MODES = ["auto", "claude", "codex"]


class FastAPIExecutorContractTest(unittest.TestCase):
    def test_claude_cmd_launcher_resolves_to_native_executable(self) -> None:
        manager = ExecutorService("auto")
        launcher = Path(r"C:\tools\npm\claude.CMD")
        native = launcher.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        with patch("app.executors.service.get_setting", return_value=str(launcher)), patch.object(
            Path, "is_file", autospec=True, side_effect=lambda value: value == native
        ):
            self.assertEqual(manager.get_command("claude"), str(native))

    def test_profile_selection_is_separate_from_executor_mode(self) -> None:
        manager = ExecutorService("auto")
        self.assertEqual(manager.get_profile("codex"), "pro")
        self.assertEqual(manager.set_profile("codex", "max"), "max")
        self.assertEqual(manager.get_mode(), "auto")
        self.assertEqual(manager.resolve_model("codex").model_id, "gpt-5.6-sol")

    def test_invalid_profile_does_not_change_selection(self) -> None:
        manager = ExecutorService("codex")
        with self.assertRaises(ValueError):
            manager.set_profile("codex", "invalid")
        self.assertEqual(manager.get_profile("codex"), "pro")

    def test_profiles_api_is_sanitized_and_updates_selection(self) -> None:
        manager = ExecutorService("auto")
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(
                create_app(
                    executor_manager=manager,
                    task_manager=_isolated_task_manager(temp_dir),
                )
            )
            try:
                initial = client.get("/api/executor/profiles")
                changed = client.post(
                    "/api/executor/profiles",
                    json={"provider": "codex", "profile": "max"},
                )
                final = client.get("/api/executor/profiles")
            finally:
                client.close()
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(changed.json(), {"ok": True, "provider": "codex", "active_profile": "max"})
        providers = {item["provider"]: item for item in final.json()["providers"]}
        self.assertEqual(providers["codex"]["active_profile"], "max")
        self.assertEqual([item["profile"] for item in providers["claude"]["profiles"]], ["max", "pro", "fast"])
        self.assertEqual(
            [item["display_name"] for item in providers["codex"]["profiles"]],
            ["GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.6 Luna"],
        )
        self.assertEqual(
            [item["display_name"] for item in providers["claude"]["profiles"]],
            ["Opus 5", "Sonnet 5", "Haiku 4.5"],
        )
        self.assertNotIn("model_id", final.text)
        self.assertNotIn("gpt-4o", final.text.lower())
        self.assertNotIn("astra", final.text.lower())
        self.assertNotIn("token", final.text.lower())

    def test_profiles_api_rejects_invalid_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(
                create_app(
                    executor_manager=ExecutorService("auto"),
                    task_manager=_isolated_task_manager(temp_dir),
                )
            )
            try:
                response = client.post(
                    "/api/executor/profiles",
                    json={"provider": "codex", "profile": "ultra"},
                )
            finally:
                client.close()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Profile inválido")

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.client = TestClient(
            create_app(task_manager=_isolated_task_manager(cls.temp_dir.name))
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temp_dir.cleanup()

    def setUp(self) -> None:
        executor_service.set_mode("auto")

    def tearDown(self) -> None:
        executor_service.set_mode("auto")

    def test_mode_auto_matches_frozen_get_contract(self) -> None:
        response = self.client.get("/api/executor/mode")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "auto", "validModes": VALID_MODES})

    def test_mode_claude_is_normalized_and_kept_in_memory(self) -> None:
        response = self.client.post("/api/executor/mode", json={"mode": " CLAUDE "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "mode": "claude"})
        self.assertEqual(self.client.get("/api/executor/mode").json()["mode"], "claude")

    def test_selecting_cold_start_claude_does_not_fabricate_operational_evidence(self) -> None:
        availability = ProviderAvailabilityService()
        availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            entitled=True,
            operational=False,
            reason="capability_not_validated",
        )
        manager = ExecutorService("codex")
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(
                create_app(
                    executor_manager=manager,
                    availability_service=availability,
                    task_manager=_isolated_task_manager(temp_dir),
                )
            )
            try:
                changed = client.post("/api/executor/mode", json={"mode": "claude"})
                health = client.get("/api/providers/health").json()["claude"]
            finally:
                client.close()

        self.assertEqual(changed.json(), {"ok": True, "mode": "claude"})
        self.assertFalse(health["operational"])
        self.assertFalse(health["eligible"])
        self.assertEqual(health["reason"], "capability_not_validated")

    def test_ai_models_panel_reflects_proven_claude_even_when_codex_is_selected(self) -> None:
        """Provider health e execution_mode sao conceitos independentes: uma vez
        que record_success() comprovou Claude operacional, selecionar CODEX como
        executor ativo nao pode "apagar" essa evidencia real do painel AI MODELS.
        Reproduz empiricamente o cenario relatado como bug (Claude "desliga"
        visualmente quando Codex esta selecionado) usando os mesmos endpoints
        reais que o frontend consome."""

        availability = ProviderAvailabilityService()
        availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            entitled=True,
            operational=False,
            reason="capability_not_validated",
        )
        availability.record_success("claude")  # simula uma execucao real bem-sucedida
        manager = ExecutorService("codex")
        with tempfile.TemporaryDirectory() as temp_dir:
            client = TestClient(
                create_app(
                    executor_manager=manager,
                    availability_service=availability,
                    task_manager=_isolated_task_manager(temp_dir),
                )
            )
            try:
                switched = client.post("/api/executor/mode", json={"mode": "codex"})
                profiles = client.get("/api/executor/profiles").json()["providers"]
            finally:
                client.close()

        self.assertEqual(switched.json(), {"ok": True, "mode": "codex"})
        claude_entry = next(item for item in profiles if item["provider"] == "claude")
        self.assertEqual(claude_entry["status"], "online")
        self.assertTrue(claude_entry["availability"])
        self.assertEqual(claude_entry["reason"], "operational")
        for profile in claude_entry["profiles"]:
            self.assertEqual(profile["status"], "online")
            self.assertTrue(profile["available"])
            self.assertTrue(profile["enabled"])

    def test_mode_codex_is_kept_in_memory_without_detecting_or_running_cli(self) -> None:
        with (
            patch("app.executors.cli.shutil.which") as lookup,
            patch("app.executors.cli.asyncio.create_subprocess_exec", new=AsyncMock()) as spawn,
        ):
            response = self.client.post("/api/executor/mode", json={"mode": "codex"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "mode": "codex"})
        lookup.assert_not_called()
        spawn.assert_not_awaited()

    def test_mode_openai_is_rejected_before_chat_execution(self) -> None:
        executor_service.set_mode("claude")

        response = self.client.post("/api/executor/mode", json={"mode": "openai"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"ok": False, "error": "Modo inválido", "validModes": VALID_MODES},
        )
        self.assertEqual(executor_service.get_mode(), "claude")

    def test_invalid_mode_returns_node_compatible_400_and_does_not_change_state(self) -> None:
        executor_service.set_mode("claude")

        response = self.client.post("/api/executor/mode", json={"mode": "local"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"ok": False, "error": "Modo inválido", "validModes": VALID_MODES},
        )
        self.assertEqual(executor_service.get_mode(), "claude")

    def test_missing_mode_uses_contract_400_instead_of_fastapi_422(self) -> None:
        response = self.client.post("/api/executor/mode", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Modo inválido")

    def test_absent_clis_are_reported_by_passive_detection(self) -> None:
        with (
            patch("app.executors.service.get_setting", return_value=None),
            patch("app.executors.cli.shutil.which", return_value=None) as lookup,
        ):
            detections = executor_service.detect_executors()

        self.assertFalse(detections["claude"].available)
        self.assertFalse(detections["codex"].available)
        self.assertIsNone(detections["claude"].path)
        self.assertGreaterEqual(lookup.call_count, 2)

    def test_explicit_codex_command_wins_over_extension_autodiscovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            bundled = (
                profile
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-99.0.0-win32-x64"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            bundled.parent.mkdir(parents=True)
            bundled.write_bytes(b"MZ")
            with patch.dict(
                os.environ,
                {
                    "USERPROFILE": str(profile),
                    "JARVIS_CODEX_CMD": r"D:\approved\codex.exe",
                },
                clear=False,
            ):
                command = ExecutorService().get_command("codex")

        self.assertEqual(command, r"D:\approved\codex.exe")

    def test_codex_command_uses_only_official_vscode_extension_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            bundled = (
                profile
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-99.0.0-win32-x64"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            bundled.parent.mkdir(parents=True)
            bundled.write_bytes(b"MZ")
            with (
                patch.dict(
                    os.environ,
                    {
                        "USERPROFILE": str(profile),
                        "JARVIS_CODEX_CMD": "",
                        "PATH": "",
                    },
                    clear=False,
                ),
            ):
                command = ExecutorService().get_command("codex")

        self.assertEqual(Path(command), bundled)

    def test_codex_discovery_ignores_executable_outside_approved_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            untrusted = profile / "Downloads" / "codex.exe"
            untrusted.parent.mkdir()
            untrusted.write_bytes(b"MZ")
            with (
                patch.dict(
                    os.environ,
                    {
                        "USERPROFILE": str(profile),
                        "JARVIS_CODEX_CMD": "",
                        "PATH": "",
                    },
                    clear=False,
                ),
            ):
                detection = ExecutorService().detect_executors()["codex"]

        self.assertFalse(detection.available)
        self.assertIsNone(detection.path)

    def test_codex_already_on_path_keeps_normal_command_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex = Path(temp_dir) / "codex.exe"
            codex.write_bytes(b"MZ")
            with patch.dict(
                os.environ,
                {"JARVIS_CODEX_CMD": "", "PATH": temp_dir},
                clear=False,
            ):
                self.assertEqual(ExecutorService().get_command("codex"), "codex")

    def test_codex_home_uses_existing_override_without_mutating_environment(self) -> None:
        before = dict(os.environ)
        with patch.dict(
            os.environ,
            {"CODEX_HOME": r"D:\profiles\approved-codex"},
            clear=False,
        ):
            environment = codex_subprocess_environment()

        self.assertEqual(environment, {"CODEX_HOME": r"D:\profiles\approved-codex"})
        self.assertEqual(dict(os.environ), before)

    def test_codex_home_defaults_to_current_windows_user_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {"USERPROFILE": temp_dir, "CODEX_HOME": ""},
                clear=False,
            ):
                environment = codex_subprocess_environment()

        self.assertEqual(environment, {"CODEX_HOME": str(Path(temp_dir) / ".codex")})

    def test_provider_health_reflects_the_in_memory_mode(self) -> None:
        executor_service.set_mode("codex")
        with patch("app.executors.cli.shutil.which", return_value=None):
            response = self.client.get("/api/providers/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["executor"]["mode"], "codex")

    def test_local_cors_preflight_allows_executor_mode_post(self) -> None:
        response = self.client.options(
            "/api/executor/mode",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:8000")
        self.assertIn("POST", response.headers["access-control-allow-methods"])

    def test_fastapi_startup_allows_passive_detection_without_running_executors(self) -> None:
        with (
            patch("app.executors.cli.shutil.which") as lookup,
            patch("app.executors.cli.asyncio.create_subprocess_exec", new=AsyncMock()) as spawn,
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                isolated_client = TestClient(
                    create_app(task_manager=_isolated_task_manager(temp_dir))
                )
                try:
                    response = isolated_client.get("/api/health")
                finally:
                    isolated_client.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["components"]["server"], {"status": "ok"})
        self.assertTrue(lookup.called)
        spawn.assert_not_awaited()


class AsyncCliExecutorFoundationTest(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_process_has_typed_error_without_real_execution(self) -> None:
        runner = AsyncCliExecutor("missing-cli-for-test")
        mocked_spawn = AsyncMock(side_effect=FileNotFoundError("missing"))

        with (
            patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn),
            self.assertRaises(CliUnavailableError),
        ):
            await runner.execute()

        mocked_spawn.assert_awaited_once()

    async def test_stdout_and_stderr_are_captured_from_simulated_process(self) -> None:
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=("saída".encode(), b"warning"))
        mocked_spawn = AsyncMock(return_value=process)

        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            result = await AsyncCliExecutor("simulated-cli").execute(["--safe"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "saída")
        self.assertEqual(result.stderr, "warning")

    async def test_codex_home_is_passed_only_to_configured_subprocess(self) -> None:
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"ok", b""))
        mocked_spawn = AsyncMock(return_value=process)
        codex_home = r"C:\Users\current\.codex"

        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            await AsyncCliExecutor(
                "codex.exe",
                environment={"CODEX_HOME": codex_home},
            ).execute()

        self.assertEqual(mocked_spawn.await_args.kwargs["env"]["CODEX_HOME"], codex_home)

    async def test_executor_without_environment_does_not_receive_codex_home(self) -> None:
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"ok", b""))
        mocked_spawn = AsyncMock(return_value=process)

        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            await AsyncCliExecutor("claude").execute()

        self.assertIsNone(mocked_spawn.await_args.kwargs.get("env"))

    async def test_subprocess_environment_does_not_mutate_python_environment(self) -> None:
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"ok", b""))
        mocked_spawn = AsyncMock(return_value=process)
        before = dict(os.environ)

        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            await AsyncCliExecutor(
                "codex.exe",
                environment={"CODEX_HOME": r"C:\Users\current\.codex"},
            ).execute()

        self.assertEqual(dict(os.environ), before)

    async def test_stdin_is_forwarded_to_simulated_process(self) -> None:
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"ok", b""))
        mocked_spawn = AsyncMock(return_value=process)

        with patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn):
            await AsyncCliExecutor("simulated-cli").execute(stdin_text="pedido")

        process.communicate.assert_awaited_once_with("pedido".encode("utf-8"))
        self.assertEqual(
            mocked_spawn.await_args.kwargs["stdin"],
            asyncio.subprocess.PIPE,
        )

    async def test_timeout_kills_simulated_process_and_preserves_captured_output(self) -> None:
        process = Mock(returncode=None)
        process.communicate = AsyncMock(
            side_effect=[asyncio.TimeoutError(), (b"partial stdout", b"partial stderr")]
        )
        mocked_spawn = AsyncMock(return_value=process)

        with (
            patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn),
            self.assertRaises(CliTimeoutError) as raised,
        ):
            await AsyncCliExecutor("simulated-cli").execute(timeout=0.01)

        process.kill.assert_called_once()
        self.assertEqual(raised.exception.stdout, "partial stdout")
        self.assertEqual(raised.exception.stderr, "partial stderr")

    async def test_cancellation_kills_simulated_process_and_is_propagated(self) -> None:
        process = Mock(returncode=None)
        process.communicate = AsyncMock(
            side_effect=[asyncio.CancelledError(), (b"discarded stdout", b"discarded stderr")]
        )
        mocked_spawn = AsyncMock(return_value=process)

        with (
            patch("app.executors.cli.asyncio.create_subprocess_exec", new=mocked_spawn),
            self.assertRaises(asyncio.CancelledError),
        ):
            await AsyncCliExecutor("simulated-cli").execute()

        process.kill.assert_called_once()
        self.assertEqual(process.communicate.await_count, 2)


if __name__ == "__main__":
    unittest.main()
