# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
browser-control.py — Chrome DevTools Protocol controller for JARVIS
Accepts JSON commands via stdin, outputs JSON results to stdout.
Connects to Chrome's debug port (CDP) for browser automation.
"""

import sys
import json
import time
import subprocess
import os
import asyncio

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def out(obj):
    """Write a JSON line to stdout and flush."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def ok(cmd, data=None):
    r = {"ok": True, "cmd": cmd}
    if data is not None:
        r["data"] = data
    out(r)


def err(cmd, msg):
    out({"ok": False, "cmd": cmd, "error": str(msg)})


# ---------------------------------------------------------------------------
# HTTP helper (stdlib only — no requests needed)
# ---------------------------------------------------------------------------

import urllib.request
import urllib.error


def http_get_json(url, timeout=5):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# URL policy (2026-09-05, decisao de seguranca — ver JARVIS_MASTER.md):
# navegacao real (Page.navigate) so e permitida para URLs absolutas com
# esquema http/https. Isso bloqueia estruturalmente javascript:, file:,
# data:, vbscript: e qualquer esquema desconhecido. Esta e a UNICA policy de
# URL de navegacao do Jarvis para este fluxo — nao duplicar em outro lugar
# (app/api/automation.py so valida QUAIS comandos podem chegar aqui, nao o
# conteudo da URL).
# ---------------------------------------------------------------------------

from urllib.parse import urlsplit

ALLOWED_NAVIGATION_URL_SCHEMES = {"http", "https"}


def is_allowed_navigation_url(url):
    """Retorna (allowed: bool, reason: str). So http(s) absoluto e permitido."""
    if not isinstance(url, str) or not url.strip():
        return False, "missing 'url'"
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "").lower()
    if not scheme:
        return False, "url deve ser absoluta (sem esquema)"
    if scheme not in ALLOWED_NAVIGATION_URL_SCHEMES:
        return False, f"esquema nao permitido: {scheme!r} (so {sorted(ALLOWED_NAVIGATION_URL_SCHEMES)})"
    if not parts.netloc:
        return False, "url deve ter um host"
    return True, ""


# ---------------------------------------------------------------------------
# Try to import websockets; set flag if unavailable
# ---------------------------------------------------------------------------

try:
    import websockets
    import websockets.sync.client as ws_sync
    HAS_WS = True
except ImportError:
    HAS_WS = False

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_port = 9222
_tabs = []          # list of tab info dicts from /json
_ws_conns = {}      # tab_index -> websocket connection
_msg_id = 0         # auto-incrementing CDP message id


def next_id():
    global _msg_id
    _msg_id += 1
    return _msg_id


# ---------------------------------------------------------------------------
# Chrome launch / detection
# ---------------------------------------------------------------------------

CHROME_PATHS = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome():
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            return p
    return None


def is_chrome_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5
        )
        return "chrome.exe" in result.stdout.lower()
    except Exception:
        return False


def is_debug_port_open(port):
    try:
        http_get_json(f"http://localhost:{port}/json/version", timeout=2)
        return True
    except Exception:
        return False


def launch_chrome(port):
    chrome = find_chrome()
    if not chrome:
        return False, "Chrome not found in standard install paths"

    if is_chrome_running():
        if is_debug_port_open(port):
            return True, "already running with debug port"
        return False, (
            f"Chrome is running but NOT with --remote-debugging-port={port}. "
            "Close all Chrome windows and let JARVIS relaunch it, or relaunch manually with: "
            f'chrome.exe --remote-debugging-port={port}'
        )

    # Launch Chrome with debug port
    subprocess.Popen(
        [chrome, f"--remote-debugging-port={port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Wait for debug port
    for _ in range(25):  # 5 seconds
        time.sleep(0.2)
        if is_debug_port_open(port):
            return True, "launched"

    return False, "Chrome launched but debug port did not open within 5s"


# ---------------------------------------------------------------------------
# CDP over WebSocket (sync wrappers around websockets library)
# ---------------------------------------------------------------------------

def ws_connect(tab_index):
    """Get or create a websocket connection for a tab index."""
    if tab_index in _ws_conns:
        try:
            _ws_conns[tab_index].ping()
            return _ws_conns[tab_index]
        except Exception:
            try:
                _ws_conns[tab_index].close()
            except Exception:
                pass
            del _ws_conns[tab_index]

    if not HAS_WS:
        raise RuntimeError("websockets library not installed — run: pip install websockets")

    if tab_index < 0 or tab_index >= len(_tabs):
        raise IndexError(f"Tab index {tab_index} out of range (have {len(_tabs)} tabs)")

    ws_url = _tabs[tab_index].get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError(f"Tab {tab_index} has no webSocketDebuggerUrl")

    conn = ws_sync.connect(ws_url, open_timeout=5, close_timeout=3)
    _ws_conns[tab_index] = conn
    return conn


def cdp_send(tab_index, method, params=None, timeout=10):
    """Send a CDP command and wait for the result."""
    conn = ws_connect(tab_index)
    mid = next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    conn.send(json.dumps(msg))

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = conn.recv(timeout=max(0.1, deadline - time.time()))
        except TimeoutError:
            break
        resp = json.loads(raw)
        if resp.get("id") == mid:
            if "error" in resp:
                raise RuntimeError(resp["error"].get("message", str(resp["error"])))
            return resp.get("result", {})
    raise TimeoutError(f"CDP call {method} timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_connect(data):
    global _port, _tabs
    _port = data.get("port", 9222)

    # Ensure Chrome is reachable
    if not is_debug_port_open(_port):
        launched, msg = launch_chrome(_port)
        if not launched:
            return err("connect", msg)

    # Fetch tab list
    try:
        raw = http_get_json(f"http://localhost:{_port}/json")
    except Exception as e:
        return err("connect", f"Failed to list tabs: {e}")

    _tabs = [t for t in raw if t.get("type") == "page"]
    ok("connect", {
        "tabs": len(_tabs),
        "message": "connected",
        "hasWebsockets": HAS_WS,
    })


def cmd_list_tabs(data):
    global _tabs
    try:
        raw = http_get_json(f"http://localhost:{_port}/json")
        _tabs = [t for t in raw if t.get("type") == "page"]
    except Exception as e:
        return err("list_tabs", f"Failed to list tabs: {e}")

    result = []
    for i, t in enumerate(_tabs):
        result.append({
            "index": i,
            "id": t.get("id", ""),
            "title": t.get("title", ""),
            "url": t.get("url", ""),
        })
    ok("list_tabs", result)


def cmd_navigate(data):
    tab = data.get("tab", 0)
    url = data.get("url", "")
    allowed, reason = is_allowed_navigation_url(url)
    if not allowed:
        return err("navigate", f"blocked by URL policy: {reason}")
    try:
        result = cdp_send(tab, "Page.navigate", {"url": url})
        # Wait a moment for navigation to begin
        time.sleep(0.5)
        ok("navigate", {"frameId": result.get("frameId", ""), "url": url})
    except Exception as e:
        err("navigate", str(e))


def cmd_get_dom(data):
    tab = data.get("tab", 0)
    selector = data.get("selector", "body")
    depth = data.get("depth", 3)

    safe_sel = json.dumps(selector)  # JSON.stringify equivalent — escapes all special chars
    js = f"""
    (function() {{
        function walk(el, d, max) {{
            if (!el || d > max) return '';
            let tag = el.tagName ? el.tagName.toLowerCase() : '';
            let id = el.id ? '#' + el.id : '';
            let cls = el.className && typeof el.className === 'string'
                ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
            let text = '';
            if (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3) {{
                let t = el.childNodes[0].textContent.trim();
                if (t.length > 0) text = ' "' + t.substring(0, 80) + '"';
            }}
            let line = '  '.repeat(d) + '<' + tag + id + cls + '>' + text;
            let children = '';
            if (d < max && el.children) {{
                for (let c of el.children) {{
                    children += '\\n' + walk(c, d + 1, max);
                }}
            }}
            return line + children;
        }}
        let sel = {safe_sel};
        let root = document.querySelector(sel);
        if (!root) return 'ERROR: selector not found: ' + sel;
        return walk(root, 0, {depth});
    }})()
    """
    try:
        result = cdp_send(tab, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        value = result.get("result", {}).get("value", "")
        ok("get_dom", {"dom": value})
    except Exception as e:
        err("get_dom", str(e))


def cmd_click(data):
    tab = data.get("tab", 0)
    selector = data.get("selector", "")
    if not selector:
        return err("click", "missing 'selector'")

    safe_sel = json.dumps(selector)
    js = f"""
    (function() {{
        let el = document.querySelector({safe_sel});
        if (!el) return JSON.stringify({{error: 'element not found'}});
        let rect = el.getBoundingClientRect();
        return JSON.stringify({{
            x: rect.x + rect.width / 2,
            y: rect.y + rect.height / 2,
            tag: el.tagName
        }});
    }})()
    """
    try:
        result = cdp_send(tab, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        val = json.loads(result.get("result", {}).get("value", "{}"))
        if "error" in val:
            return err("click", val["error"])

        x, y = val["x"], val["y"]

        # Dispatch mouse events: move, press, release
        for etype in ["mouseMoved", "mousePressed", "mouseReleased"]:
            params = {
                "type": etype,
                "x": x, "y": y,
                "button": "left",
                "clickCount": 1,
            }
            cdp_send(tab, "Input.dispatchMouseEvent", params, timeout=3)

        ok("click", {"selector": selector, "x": x, "y": y, "tag": val.get("tag", "")})
    except Exception as e:
        err("click", str(e))


def cmd_fill(data):
    tab = data.get("tab", 0)
    selector = data.get("selector", "")
    value = data.get("value", "")
    if not selector:
        return err("fill", "missing 'selector'")

    safe_val = json.dumps(value)
    safe_sel = json.dumps(selector)

    js = f"""
    (function() {{
        let sel = {safe_sel};
        let el = document.querySelector(sel);
        if (!el) return JSON.stringify({{error: 'element not found: ' + sel}});
        el.focus();
        el.value = {safe_val};
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return JSON.stringify({{ok: true, tag: el.tagName, selector: sel}});
    }})()
    """
    try:
        result = cdp_send(tab, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        val = json.loads(result.get("result", {}).get("value", "{}"))
        if "error" in val:
            return err("fill", val["error"])
        ok("fill", val)
    except Exception as e:
        err("fill", str(e))


def cmd_get_text(data):
    tab = data.get("tab", 0)
    selector = data.get("selector", "")
    if not selector:
        return err("get_text", "missing 'selector'")

    safe_sel = json.dumps(selector)
    js = f"""
    (function() {{
        let sel = {safe_sel};
        let el = document.querySelector(sel);
        if (!el) return JSON.stringify({{error: 'element not found: ' + sel}});
        return JSON.stringify({{text: el.textContent}});
    }})()
    """
    try:
        result = cdp_send(tab, "Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
        })
        val = json.loads(result.get("result", {}).get("value", "{}"))
        if "error" in val:
            return err("get_text", val["error"])
        ok("get_text", {"text": val.get("text", ""), "selector": selector})
    except Exception as e:
        err("get_text", str(e))


# cmd_execute_js (executava QUALQUER JavaScript recebido no payload via
# Runtime.evaluate) foi REMOVIDA em 2026-09-05 por decisao de seguranca:
# ARBITRARY JAVASCRIPT VIA API = FORBIDDEN (ver JARVIS_MASTER.md). Operacoes
# de browser continuam permitidas, mas so como acoes bounded e nomeadas
# (navigate com URL policy, click/fill/get_text por selector, get_dom,
# wait_for, screenshot) — nunca um "code"/"expression" livre. Nao recriar.


def cmd_wait_for(data):
    tab = data.get("tab", 0)
    selector = data.get("selector", "")
    timeout_ms = data.get("timeout", 5000)
    if not selector:
        return err("wait_for", "missing 'selector'")

    safe_sel = json.dumps(selector)
    js = f"!!document.querySelector({safe_sel})"
    deadline = time.time() + (timeout_ms / 1000)

    try:
        while time.time() < deadline:
            result = cdp_send(tab, "Runtime.evaluate", {
                "expression": js,
                "returnByValue": True,
            }, timeout=3)
            found = result.get("result", {}).get("value", False)
            if found:
                return ok("wait_for", {"selector": selector, "found": True})
            time.sleep(0.2)

        err("wait_for", f"Timeout: '{selector}' not found within {timeout_ms}ms")
    except Exception as e:
        err("wait_for", str(e))


def cmd_screenshot(data):
    tab = data.get("tab", 0)
    try:
        result = cdp_send(tab, "Page.captureScreenshot", {
            "format": "png",
            "quality": 80,
        }, timeout=10)
        b64 = result.get("data", "")
        ok("screenshot", {"base64": b64, "format": "png", "length": len(b64)})
    except Exception as e:
        err("screenshot", str(e))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    "connect": cmd_connect,
    "list_tabs": cmd_list_tabs,
    "navigate": cmd_navigate,
    "get_dom": cmd_get_dom,
    "click": cmd_click,
    "fill": cmd_fill,
    "get_text": cmd_get_text,
    # "execute_js" removida em 2026-09-05 (decisao de seguranca) — ver comentario acima.
    "wait_for": cmd_wait_for,
    "screenshot": cmd_screenshot,
}


def dispatch(line):
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        out({"ok": False, "cmd": "?", "error": f"Invalid JSON: {e}"})
        return

    cmd = data.get("cmd", "")
    handler = COMMANDS.get(cmd)
    if not handler:
        out({"ok": False, "cmd": cmd, "error": f"Unknown command: {cmd}"})
        return

    try:
        handler(data)
    except Exception as e:
        err(cmd, str(e))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    # Auto-connect on startup
    if "--auto-connect" in sys.argv:
        cmd_connect({"port": 9222})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.lower() in ("quit", "exit"):
            break
        dispatch(line)

    # Cleanup websocket connections
    for idx, conn in _ws_conns.items():
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
