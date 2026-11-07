"""Garante que contratos ativos nao caiam no fallback StaticFiles."""

import re
import tempfile
import unittest
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.main import create_app
from app.tasks.manager import TaskManager


def _create_app_with_isolated_task_manager():
    """create_app() sem task_manager= constroi um TaskManager real ligado a
    system/task-state.json (e o le/reconcilia no __init__). Estes testes so
    inspecionam o *shape* das rotas, nunca fazem chamadas HTTP, mas mesmo
    assim nao podem tocar o arquivo de producao para montar o app."""

    with tempfile.TemporaryDirectory() as temp_dir:
        manager = TaskManager(Path(temp_dir) / "task-state.json")
        return create_app(task_manager=manager)


def explicit_routes(app):
    found = set()
    for item in app.routes:
        container = getattr(item, "original_router", item)
        for route in getattr(container, "routes", [item]):
            path = getattr(route, "path", None)
            for method in getattr(route, "methods", set()) or set():
                if path and path.startswith("/api/"):
                    found.add((method, path))
    return found


class FrontendParityTests(unittest.TestCase):
    def test_model_profiles_are_backend_driven_without_technical_ids(self):
        for element_id in ("profile-codex-max", "profile-codex-pro", "profile-codex-fast", "profile-claude-max", "profile-claude-pro", "profile-claude-fast"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.index)
        self.assertIn("/api/executor/profiles", self.frontend)
        for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            self.assertNotIn(model_id, self.index)
            self.assertNotIn(model_id, self.frontend)

    def test_ai_models_panel_is_rendered_from_profiles_api_without_legacy_catalog(self):
        panel = self.index.split('<div class="panel jarvas-ai-models-panel">', 1)[1].split('</aside>', 1)[0]
        self.assertIn('id="ai-model-catalog"', panel)
        for legacy in ("GPT-4o RT", "GPT-4o-mini", "Opus 4.7", "Sonnet 4.6", "Haiku 4.5", "DEEP", "BUILD", "VOICE", "QUICK"):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, panel)
        self.assertIn("renderAiModelCatalog", self.frontend)
        self.assertIn("name.textContent = profile.display_name;", self.frontend)
        self.assertNotIn("profile.display_name || profile.profile", self.frontend)
        self.assertIn("provider.status", self.frontend)

    def test_ai_models_selection_comes_from_backend_active_profile(self):
        renderer = self.frontend.split("function renderAiModelCatalog", 1)[1].split("function renderModelProfiles", 1)[0]
        self.assertIn("provider.active_profile === profile.profile", renderer)
        self.assertIn("row.classList.toggle('selected'", renderer)
        self.assertNotIn("profile.available ? 'selected'", renderer)

    def test_ai_models_badges_have_one_fixed_size_structural_class(self):
        renderer = self.frontend.split("function renderAiModelCatalog", 1)[1].split("function renderModelProfiles", 1)[0]
        self.assertIn("model-profile-badge", renderer)
        badge_css = re.search(r"\.model-profile-badge\s*\{([^}]+)\}", self.index)
        self.assertIsNotNone(badge_css)
        rules = badge_css.group(1)
        self.assertRegex(rules, r"width:\s*\d+px")
        self.assertRegex(rules, r"height:\s*\d+px")
        self.assertIn("display:inline-flex", rules.replace(" ", ""))
        self.assertIn("align-items:center", rules.replace(" ", ""))
        self.assertIn("justify-content:center", rules.replace(" ", ""))
        self.assertIn("box-sizing:border-box", rules.replace(" ", ""))

    def test_model_statuses_are_not_hardcoded_online(self):
        self.assertNotIn("['CODEX', 'available']", self.index)
        self.assertNotIn('<span class="ttb-badge">ONLINE</span>', self.index)
        for status in ("online", "offline", "not_authenticated", "entitlement_unavailable", "profile_unavailable", "model_unavailable", "checking", "unknown"):
            self.assertIn(status, self.frontend)
    def setUp(self):
        self.frontend = (PROJECT_ROOT / "public" / "script.js").read_text(encoding="utf-8")
        self.index = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

    def test_all_active_frontend_contracts_are_explicit_fastapi_routes(self):
        source = self.frontend
        calls = set()
        for match in re.finditer(r"fetch\(\s*['\"](/api/[^'\"?]+)", source):
            tail = source[match.end():match.end() + 180]
            method_match = re.search(r"method\s*:\s*['\"](GET|POST|PUT|DELETE)['\"]", tail)
            calls.add(((method_match.group(1) if method_match else "GET"), match.group(1)))
        calls.discard(("GET", "/api/chat"))  # exemplo em comentario; chamada real e POST
        routes = explicit_routes(_create_app_with_isolated_task_manager())
        missing = sorted(calls - routes)
        self.assertEqual(missing, [], f"Contratos sem rota FastAPI explicita: {missing}")

    def test_reported_auxiliary_contracts_are_registered(self):
        routes = explicit_routes(_create_app_with_isolated_task_manager())
        expected = {
            ("GET", "/api/agenda/balance"),
            ("GET", "/api/notifications"),
            ("GET", "/api/obsidian/stats"),
            ("GET", "/api/weather"),
            ("POST", "/api/realtime/session"),
        }
        self.assertEqual(expected - routes, set())

    def test_realtime_uses_current_audio_events_with_safe_legacy_aliases(self):
        for event_type in (
            "response.output_audio.delta",
            "response.output_audio.done",
            "response.output_audio_transcript.done",
            "response.done",
        ):
            with self.subTest(event_type=event_type):
                self.assertTrue(event_type in self.frontend, f"Evento Realtime ausente: {event_type}")

        self.assertTrue("startsWith('response.audio.')" not in self.frontend, "Matcher legado ainda e o handler principal")
        self.assertTrue("REALTIME_AUDIO_START_EVENTS" in self.frontend)
        self.assertTrue("REALTIME_AUDIO_DONE_EVENTS" in self.frontend)
        self.assertTrue("REALTIME_TRANSCRIPT_DONE_EVENTS" in self.frontend)

    def test_realtime_speaking_lifecycle_is_idempotent(self):
        self.assertTrue(re.search(
            r"function beginRealtimeResponse\(\)\s*\{[^}]*isJarvisSpeaking\s*=\s*true;[^}]*setAvatarState\('speaking'\);",
            self.frontend,
        ), "Inicio de audio nao ativa o estado de fala")
        self.assertTrue(re.search(
            r"function finishRealtimeResponse\(\)\s*\{[^}]*isJarvisSpeaking\s*=\s*false;[^}]*setAvatarState\(realtimeActive \? 'listening' : 'idle'\);",
            self.frontend,
        ), "Fim da resposta nao encerra a fala e retoma a escuta quando a sessao esta ativa")
        self.assertTrue(re.search(
            r"if \(ev\.type === 'response\.done'\) finishRealtimeResponse\(\);",
            self.frontend,
        ), "response.done nao encerra o turno")

    def test_voice_state_machine_uses_only_official_states_and_starts_muted(self):
        self.assertIn(
            "const VOICE_STATUS_STATES = ['mute', 'connecting', 'listening', 'thinking', 'speaking'];",
            self.frontend,
        )
        self.assertNotIn("ready: 'PRONTO'", self.frontend)
        self.assertIn("function setVoiceStatus(state = 'mute')", self.frontend)
        self.assertIn("setVoiceStatus('mute');", self.frontend)
        for element_id in (
            "jarvis-core-voice-status",
            "side-voice-status",
            "jarvis-bottom-voice-status",
            "config-voice-live-status",
        ):
            with self.subTest(element_id=element_id):
                self.assertRegex(
                    self.index,
                    rf'id="{element_id}"[^>]*>MUTE<',
                    f"Estado inicial de {element_id} nao e MUTE",
                )

    def test_voice_rest_state_reflects_the_real_realtime_session(self):
        rest_state = re.search(
            r"function getVoiceRestStatus\(\)\s*\{(?P<body>.*?)\n\}",
            self.frontend,
            re.DOTALL,
        )
        self.assertIsNotNone(rest_state)
        self.assertIn("return realtimeActive ? 'listening' : 'mute';", rest_state.group("body"))
        self.assertNotIn("return 'ready'", rest_state.group("body"))

    def test_voice_state_colors_keep_mute_red_and_listening_green(self):
        self.assertRegex(
            self.index,
            r"\.mic-btn\.voice-status-mute\{[^}]*color:#ff7b86;",
            "MUTE perdeu a indicacao vermelha",
        )
        for selector in (
            r"#jarvis-mic-dot\.voice-status-listening",
            r"#jarvis-core-voice-status\.voice-status-listening",
            r"\.mic-btn\.voice-status-listening",
        ):
            with self.subTest(selector=selector):
                self.assertRegex(
                    self.index,
                    selector + r"\{[^}]*color:#39ff88;",
                    "OUVINDO nao usa a indicacao verde oficial",
                )

    def test_realtime_events_drive_connecting_listening_thinking_and_speaking(self):
        for contract in (
            "setVoiceStatus('connecting')",
            "setVoiceStatus('listening')",
            "input_audio_buffer.speech_stopped",
            "setVoiceStatus('thinking')",
            "REALTIME_AUDIO_START_EVENTS.has(ev.type)",
            "isJarvisSpeaking = true",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.frontend)
        self.assertTrue(re.search(
            r"function finishRealtimeResponse\(\)\s*\{.*?isJarvisSpeaking\s*=\s*false;.*?setAvatarState\(realtimeActive \? 'listening' : 'idle'\);.*?\}",
            self.frontend,
            re.DOTALL,
        ), "Fim do audio nao retorna a sessao ativa para OUVINDO")

    def test_click_during_any_active_state_cancels_to_mute(self):
        toggle = self.frontend.split("async function toggleVoiceCapture()", 1)[1].split("// ========== OPENAI CREDIT BALANCE", 1)[0]
        self.assertIn("if (realtimeConnecting || realtimeActive)", toggle)
        self.assertIn("realtimeUserDisabled = true;", toggle)
        self.assertIn("stopRealtime();", toggle)
        self.assertNotIn("ainda est\u00e1 em andamento", toggle)

    def test_connect_attempts_are_unique_and_cancellable(self):
        self.assertIn("let realtimeConnectionAttempt = 0;", self.frontend)
        self.assertIn("if (realtimeActive || realtimeConnecting) return;", self.frontend)
        self.assertIn("assertRealtimeConnectionAttempt(connectionAttempt)", self.frontend)
        self.assertIn("error.code = 'REALTIME_CONNECT_CANCELLED'", self.frontend)

    def test_fatal_realtime_failures_cleanup_to_mute(self):
        self.assertIn("function stopRealtime()", self.frontend)
        self.assertIn("setVoiceStatus('mute');", self.frontend)
        self.assertIn("failRealtimeTransport('session'", self.frontend)
        self.assertNotIn("stopRealtime('error')", self.frontend)
        self.assertNotIn("stopRealtime(micError.state)", self.frontend)

    def test_realtime_peer_and_data_channel_failures_cleanup_resources(self):
        for event_name in ("connectionstatechange", "iceconnectionstatechange"):
            with self.subTest(event_name=event_name):
                self.assertTrue(event_name in self.frontend, f"Handler ausente: {event_name}")
        for data_event in ("open", "close", "error"):
            with self.subTest(data_event=data_event):
                self.assertTrue(re.search(
                    rf"dc\.addEventListener\('{data_event}'",
                    self.frontend,
                ), f"Handler do data channel ausente: {data_event}")
        self.assertTrue("stopRealtime();" in self.frontend)
        self.assertTrue("realtimeStream?.getTracks().forEach(t => t.stop())" in self.frontend)

    def test_realtime_event_errors_are_logged_without_event_payload(self):
        realtime_section = self.frontend.split("// ========== REALTIME VOICE MODE", 1)[1].split("async function routeVoiceCommand", 1)[0]
        self.assertTrue("catch {}" not in realtime_section, "Erro do fluxo Realtime ainda e silenciado")
        self.assertTrue("[JARVIS] Realtime event handling failed:" in self.frontend)
        self.assertTrue("console.error('[JARVIS] Realtime event handling failed:', ev)" not in self.frontend)
        self.assertTrue("(?:sk|ek)(?:-|_)" in self.frontend, "Sanitizacao nao cobre chaves OpenAI com hifen e underscore")

    def test_task_metrics_use_backend_summary_without_local_task_counter(self):
        metrics = self.frontend.split("async function updateMetrics()", 1)[1].split(
            "// ── System Stats", 1
        )[0]
        self.assertIn("fetch('/api/tasks/summary'", metrics)
        self.assertIn("taskData.tasks", metrics)
        self.assertIn("taskData.executor", metrics)
        self.assertIn("taskData.last_task", metrics)
        self.assertIn("taskData.active_tasks", metrics)
        self.assertIn("started_at", self.frontend)
        self.assertIn("created_at", self.frontend)
        self.assertNotRegex(metrics, r"tasks\s*[+][+]|tasks\s*[+]=")

    def test_uptime_metric_is_derived_only_from_backend_stats(self):
        metrics = self.frontend.split("async function updateMetrics()", 1)[1].split(
            "// ── System Stats", 1
        )[0]
        self.assertIn("fetch('/api/stats'", metrics)
        self.assertIn("syncBackendUptime(data)", metrics)
        self.assertNotIn("Date.now()", metrics)

    def test_metrics_tasks_card_is_keyboard_clickable_and_renders_active_list(self):
        self.assertIn('id="metric-tasks-card"', self.index)
        self.assertIn('id="active-tasks-panel"', self.index)
        self.assertIn("renderActiveTasks", self.frontend)
        self.assertIn("formatTaskElapsed", self.frontend)
        self.assertIn("event.key === 'Enter' || event.key === ' '", self.frontend)

    def test_uptime_is_locally_ticked_from_authoritative_backend_anchor(self):
        self.assertIn("uptime_seconds", self.frontend)
        self.assertIn("syncBackendUptime", self.frontend)
        self.assertIn("renderBackendUptime", self.frontend)

    def test_openai_balance_keeps_cached_value_during_stale_refresh(self):
        balance = self.frontend.split("// ========== OPENAI CREDIT BALANCE ==========", 1)[1].split(
            "if (micBtn)", 1
        )[0]
        self.assertIn("data.balance_usd", balance)
        self.assertNotIn("data.stale ||", balance)
        self.assertIn("US$ --", balance)


if __name__ == "__main__":
    unittest.main()
