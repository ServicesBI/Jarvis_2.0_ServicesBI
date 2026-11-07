# -*- coding: utf-8 -*-
"""JARVIS Computer Use — Intelligent Action Executor.

Accepts a JSON batch of actions via stdin and executes them sequentially
using multiple strategies: Win32 API, pyautogui, UIAutomation.

SECURITY (2026-09-05, JARVIS_MASTER.md secao de seguranca / decisao
arquitetural do usuario): execucao de shell arbitrario via este executor foi
REMOVIDA de proposito (havia uma acao "shell" que rodava
subprocess.Popen(cmd, shell=True) com o comando vindo direto de uma
requisicao HTTP nao autenticada — ver app/api/automation.py::workflow e
::computer_use_task). Nao reintroduzir uma acao de shell/exec/eval aqui;
toda automacao de desktop deve continuar sendo uma acao bounded e nomeada
(click, type, key, scroll, app_focus, etc.), nunca um comando textual livre.

Usage:
    echo '{"actions":[{"type":"app_focus","title":"Notepad"}]}' | python ui-automation.py
"""

import sys
import json
import time
import ctypes
import ctypes.wintypes
import subprocess
import os

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Lazy imports — only load heavy libs when actually needed
# ---------------------------------------------------------------------------

_pyautogui = None
_pyperclip = None
_uia = None


def get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        _pyautogui = pyautogui
    return _pyautogui


def get_pyperclip():
    global _pyperclip
    if _pyperclip is None:
        import pyperclip
        _pyperclip = pyperclip
    return _pyperclip


def get_uia():
    global _uia
    if _uia is None:
        import uiautomation as auto
        _uia = auto
    return _uia


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32

SW_RESTORE = 9
SW_SHOW = 5
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
WM_CLOSE = 0x0010
GW_OWNER = 4
SMTO_ABORTIFHUNG = 0x0002

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
SetForegroundWindow = user32.SetForegroundWindow
ShowWindow = user32.ShowWindow
PostMessageW = user32.PostMessageW
GetWindow = user32.GetWindowW if hasattr(user32, "GetWindowW") else user32.GetWindow
IsIconic = user32.IsIconic


def _get_window_title(hwnd: int) -> str:
    length = GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_window_by_title(title: str) -> int | None:
    """Find first visible top-level window whose title contains `title` (case-insensitive)."""
    title_lower = title.lower()
    result = []

    def callback(hwnd, _):
        if IsWindowVisible(hwnd):
            wt = _get_window_title(hwnd)
            if wt and title_lower in wt.lower():
                result.append(hwnd)
                return False  # stop enumeration
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return result[0] if result else None


def find_all_windows_by_title(title: str) -> list[int]:
    """Find all visible top-level windows whose title contains `title`."""
    title_lower = title.lower()
    result = []

    def callback(hwnd, _):
        if IsWindowVisible(hwnd):
            wt = _get_window_title(hwnd)
            if wt and title_lower in wt.lower():
                result.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return result


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

# action_shell (subprocess.Popen(cmd, shell=True) sobre um comando vindo
# direto do payload da requisicao) foi REMOVIDA em 2026-09-05 por decisao de
# seguranca — ver o docstring do modulo. Nao recriar.


def action_app_focus(act: dict) -> dict:
    title = act.get("title", "")
    if not title:
        return {"ok": False, "error": "missing 'title'"}
    hwnd = find_window_by_title(title)
    if not hwnd:
        return {"ok": False, "error": f"window '{title}' not found"}
    wt = _get_window_title(hwnd)
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
    else:
        ShowWindow(hwnd, SW_SHOW)
    SetForegroundWindow(hwnd)
    return {"ok": True, "detail": f"focused: {wt}"}


def action_app_close(act: dict) -> dict:
    title = act.get("title", "")
    if not title:
        return {"ok": False, "error": "missing 'title'"}
    hwnds = find_all_windows_by_title(title)
    if not hwnds:
        return {"ok": False, "error": f"window '{title}' not found"}
    closed = []
    for hwnd in hwnds:
        wt = _get_window_title(hwnd)
        PostMessageW(hwnd, WM_CLOSE, 0, 0)
        closed.append(wt)
    return {"ok": True, "detail": f"closed {len(closed)} window(s): {', '.join(closed[:3])}"}


def action_app_minimize(act: dict) -> dict:
    title = act.get("title", "")
    if not title:
        return {"ok": False, "error": "missing 'title'"}
    hwnd = find_window_by_title(title)
    if not hwnd:
        return {"ok": False, "error": f"window '{title}' not found"}
    wt = _get_window_title(hwnd)
    ShowWindow(hwnd, SW_MINIMIZE)
    return {"ok": True, "detail": f"minimized: {wt}"}


def action_app_maximize(act: dict) -> dict:
    title = act.get("title", "")
    if not title:
        return {"ok": False, "error": "missing 'title'"}
    hwnd = find_window_by_title(title)
    if not hwnd:
        return {"ok": False, "error": f"window '{title}' not found"}
    wt = _get_window_title(hwnd)
    ShowWindow(hwnd, SW_MAXIMIZE)
    return {"ok": True, "detail": f"maximized: {wt}"}


def action_key(act: dict) -> dict:
    keys_str = act.get("keys", "")
    if not keys_str:
        return {"ok": False, "error": "missing 'keys'"}
    pag = get_pyautogui()
    parts = [k.strip() for k in keys_str.split("+")]
    pag.hotkey(*parts)
    return {"ok": True, "detail": f"pressed: {keys_str}"}


def _clipboard_set_utf16(text: str):
    """Set clipboard using Win32 API with proper UTF-16 encoding (handles all accents/unicode)."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13

    if not u32.OpenClipboard(0):
        raise OSError("Failed to open clipboard")
    try:
        u32.EmptyClipboard()

        # Encode as UTF-16-LE (Windows native)
        encoded = text.encode("utf-16-le") + b"\x00\x00"
        h = k32.GlobalAlloc(0x0042, len(encoded))  # GMEM_MOVEABLE | GMEM_ZEROINIT
        ptr = k32.GlobalLock(h)
        ctypes.memmove(ptr, encoded, len(encoded))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        u32.CloseClipboard()


def action_type(act: dict) -> dict:
    text = act.get("text", "")
    if not text:
        return {"ok": False, "error": "missing 'text'"}
    pag = get_pyautogui()

    # Use Win32 clipboard directly for proper UTF-16 (handles ã, é, ç, etc.)
    try:
        _clipboard_set_utf16(text)
    except Exception:
        # Fallback to pyperclip
        clip = get_pyperclip()
        clip.copy(text)

    time.sleep(0.05)
    pag.hotkey("ctrl", "v")
    time.sleep(0.1)
    return {"ok": True, "detail": f"typed {len(text)} chars"}


def action_click(act: dict) -> dict:
    x = act.get("x")
    y = act.get("y")
    if x is None or y is None:
        return {"ok": False, "error": "missing 'x' or 'y'"}
    pag = get_pyautogui()
    button = act.get("button", "left")
    clicks = act.get("clicks", 1)
    pag.click(int(x), int(y), clicks=clicks, button=button)
    return {"ok": True, "detail": f"clicked ({x},{y}) button={button}"}


def action_scroll(act: dict) -> dict:
    pag = get_pyautogui()
    direction = act.get("direction", "down")
    amount = act.get("amount", 3)
    x = act.get("x")
    y = act.get("y")
    scroll_val = amount if direction == "up" else -amount
    kwargs = {}
    if x is not None and y is not None:
        kwargs["x"] = int(x)
        kwargs["y"] = int(y)
    pag.scroll(scroll_val, **kwargs)
    return {"ok": True, "detail": f"scrolled {direction} {amount}"}


def action_wait(act: dict) -> dict:
    ms = act.get("ms", 1000)
    time.sleep(ms / 1000.0)
    return {"ok": True, "detail": f"waited {ms}ms"}


def action_wait_for(act: dict) -> dict:
    title_contains = act.get("title_contains", "")
    timeout = act.get("timeout", 5000)
    if not title_contains:
        return {"ok": False, "error": "missing 'title_contains'"}
    deadline = time.time() + (timeout / 1000.0)
    while time.time() < deadline:
        hwnd = find_window_by_title(title_contains)
        if hwnd:
            wt = _get_window_title(hwnd)
            return {"ok": True, "detail": f"found: {wt}"}
        time.sleep(0.2)
    return {"ok": False, "error": f"timeout waiting for '{title_contains}' ({timeout}ms)"}


def action_screenshot(act: dict) -> dict:
    mode = act.get("mode", "1")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    screenshot_py = os.path.join(script_dir, "screenshot.py")
    if not os.path.exists(screenshot_py):
        return {"ok": False, "error": "screenshot.py not found"}
    try:
        proc = subprocess.run(
            [sys.executable, screenshot_py, str(mode)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip())
            return {"ok": True, "detail": data}
        else:
            return {"ok": False, "error": proc.stderr.strip()[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# UIAutomation action handlers
# ---------------------------------------------------------------------------

def _uia_find_window(title: str):
    """Find a UIAutomation window control by partial title match."""
    auto = get_uia()
    # Try exact Name first
    win = auto.WindowControl(searchDepth=1, Name=title, searchInterval=0.3, foundIndex=1)
    if win.Exists(0, 0):
        return win
    # Try partial match via RegexName
    import re
    pattern = re.escape(title)
    win = auto.WindowControl(searchDepth=1, RegexName=f".*{pattern}.*", searchInterval=0.3, foundIndex=1)
    if win.Exists(0, 0):
        return win
    return None


def _uia_find_element(window, act: dict):
    """Find element within window by name and optional control_type."""
    auto = get_uia()
    name = act.get("name", "")
    control_type = act.get("control_type", "")

    if control_type:
        # Map control type string to uiautomation control class
        ctrl_map = {
            "Button": "ButtonControl",
            "Edit": "EditControl",
            "Text": "TextControl",
            "MenuItem": "MenuItemControl",
            "Menu": "MenuControl",
            "ListItem": "ListItemControl",
            "List": "ListControl",
            "TreeItem": "TreeItemControl",
            "Tree": "TreeControl",
            "Tab": "TabControl",
            "TabItem": "TabItemControl",
            "CheckBox": "CheckBoxControl",
            "RadioButton": "RadioButtonControl",
            "ComboBox": "ComboBoxControl",
            "Hyperlink": "HyperlinkControl",
            "Document": "DocumentControl",
            "Pane": "PaneControl",
            "Group": "GroupControl",
            "Slider": "SliderControl",
            "Spinner": "SpinnerControl",
            "ToolBar": "ToolBarControl",
            "StatusBar": "StatusBarControl",
            "DataGrid": "DataGridControl",
            "DataItem": "DataItemControl",
            "Window": "WindowControl",
            "Custom": "CustomControl",
        }
        ctrl_class_name = ctrl_map.get(control_type, control_type + "Control")
        ctrl_class = getattr(window, ctrl_class_name, None)
        if ctrl_class and callable(ctrl_class):
            elem = ctrl_class(Name=name, searchInterval=0.3, foundIndex=1)
            if elem.Exists(0, 0):
                return elem
    # Fallback: search by name across all control types
    auto_mod = get_uia()
    elem = window.Control(Name=name, searchInterval=0.3, foundIndex=1)
    if elem.Exists(0, 0):
        return elem
    return None


def action_uia_click(act: dict) -> dict:
    win_title = act.get("window", "")
    name = act.get("name", "")
    if not win_title or not name:
        return {"ok": False, "error": "missing 'window' or 'name'"}
    win = _uia_find_window(win_title)
    if not win:
        return {"ok": False, "error": f"window '{win_title}' not found"}
    elem = _uia_find_element(win, act)
    if not elem:
        return {"ok": False, "error": f"element '{name}' not found in '{win_title}'"}
    try:
        elem.Click(simulateMove=False)
        return {"ok": True, "detail": f"clicked '{name}' in '{win_title}'"}
    except Exception as e:
        # Fallback: click at element center via pyautogui
        try:
            rect = elem.BoundingRectangle
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            pag = get_pyautogui()
            pag.click(cx, cy)
            return {"ok": True, "detail": f"clicked '{name}' at ({cx},{cy}) via fallback"}
        except Exception as e2:
            return {"ok": False, "error": f"click failed: {e2}"}


def action_uia_set_value(act: dict) -> dict:
    win_title = act.get("window", "")
    name = act.get("name", "")
    value = act.get("value", "")
    if not win_title or not name:
        return {"ok": False, "error": "missing 'window' or 'name'"}
    win = _uia_find_window(win_title)
    if not win:
        return {"ok": False, "error": f"window '{win_title}' not found"}
    elem = _uia_find_element(win, act)
    if not elem:
        return {"ok": False, "error": f"element '{name}' not found in '{win_title}'"}
    try:
        auto = get_uia()
        vp = elem.GetValuePattern()
        if vp:
            vp.SetValue(value)
            return {"ok": True, "detail": f"set '{name}' = '{value[:50]}'"}
    except Exception:
        pass
    # Fallback: click element, select all, type value
    try:
        elem.Click(simulateMove=False)
        time.sleep(0.1)
        pag = get_pyautogui()
        pag.hotkey("ctrl", "a")
        time.sleep(0.05)
        clip = get_pyperclip()
        clip.copy(value)
        pag.hotkey("ctrl", "v")
        return {"ok": True, "detail": f"set '{name}' = '{value[:50]}' (via paste)"}
    except Exception as e:
        return {"ok": False, "error": f"set_value failed: {e}"}


def action_uia_get_text(act: dict) -> dict:
    win_title = act.get("window", "")
    name = act.get("name", "")
    if not win_title:
        return {"ok": False, "error": "missing 'window'"}
    win = _uia_find_window(win_title)
    if not win:
        return {"ok": False, "error": f"window '{win_title}' not found"}
    if name:
        elem = _uia_find_element(win, act)
        if not elem:
            return {"ok": False, "error": f"element '{name}' not found in '{win_title}'"}
    else:
        elem = win
    # Try ValuePattern
    try:
        vp = elem.GetValuePattern()
        if vp:
            val = vp.Value
            if val:
                return {"ok": True, "detail": val[:2000]}
    except Exception:
        pass
    # Try TextPattern
    try:
        tp = elem.GetTextPattern()
        if tp:
            val = tp.DocumentRange.GetText(-1)
            if val:
                return {"ok": True, "detail": val[:2000]}
    except Exception:
        pass
    # Fallback: Name property
    try:
        return {"ok": True, "detail": elem.Name[:2000] if elem.Name else ""}
    except Exception as e:
        return {"ok": False, "error": f"get_text failed: {e}"}


def action_uia_tree(act: dict) -> dict:
    win_title = act.get("window", "")
    max_depth = act.get("depth", 3)
    if not win_title:
        return {"ok": False, "error": "missing 'window'"}
    win = _uia_find_window(win_title)
    if not win:
        return {"ok": False, "error": f"window '{win_title}' not found"}

    def traverse(element, depth: int, max_d: int) -> list:
        if depth > max_d:
            return []
        nodes = []
        try:
            children = element.GetChildren()
        except Exception:
            children = []
        for child in children:
            try:
                node = {
                    "name": child.Name or "",
                    "type": child.ControlTypeName or "",
                }
                rect = child.BoundingRectangle
                if rect and rect.width() > 0:
                    node["rect"] = {
                        "x": rect.left,
                        "y": rect.top,
                        "w": rect.width(),
                        "h": rect.height(),
                    }
                # Get value if available
                try:
                    vp = child.GetValuePattern()
                    if vp and vp.Value:
                        node["value"] = vp.Value[:200]
                except Exception:
                    pass
                sub = traverse(child, depth + 1, max_d)
                if sub:
                    node["children"] = sub
                # Only include named or interactive elements to reduce noise
                if node["name"] or node.get("value") or sub or node["type"] in (
                    "ButtonControl", "EditControl", "MenuItemControl",
                    "CheckBoxControl", "RadioButtonControl", "ComboBoxControl",
                    "ListItemControl", "TabItemControl", "HyperlinkControl",
                    "SliderControl", "SpinnerControl",
                ):
                    nodes.append(node)
            except Exception:
                continue
        return nodes

    tree = traverse(win, 1, max_depth)
    return {"ok": True, "detail": tree}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

HANDLERS = {
    # "shell" removida em 2026-09-05 (decisao de seguranca) — nunca reintroduzir
    # execucao de comando textual arbitrario aqui. Ver docstring do modulo.
    "app_focus": action_app_focus,
    "app_close": action_app_close,
    "app_minimize": action_app_minimize,
    "app_maximize": action_app_maximize,
    "key": action_key,
    "type": action_type,
    "click": action_click,
    "scroll": action_scroll,
    "wait": action_wait,
    "wait_for": action_wait_for,
    "screenshot": action_screenshot,
    "uia_click": action_uia_click,
    "uia_set_value": action_uia_set_value,
    "uia_get_text": action_uia_get_text,
    "uia_tree": action_uia_tree,
}


def emit(obj: dict):
    print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        emit({"done": True, "total": 0, "success": 0, "failed": 1, "error": f"invalid JSON input: {e}"})
        return
    except Exception as e:
        emit({"done": True, "total": 0, "success": 0, "failed": 1, "error": str(e)})
        return

    actions = payload.get("actions", [])
    if not actions:
        emit({"done": True, "total": 0, "success": 0, "failed": 0})
        return

    take_screenshot_before = payload.get("screenshot_before", False)
    take_screenshot_after = payload.get("screenshot_after", False)

    # Optional screenshot before batch
    if take_screenshot_before:
        res = action_screenshot({"mode": "1"})
        emit({"idx": -1, "type": "screenshot_before", **res})

    success_count = 0
    fail_count = 0

    for idx, act in enumerate(actions):
        act_type = act.get("type", "unknown")
        handler = HANDLERS.get(act_type)
        if not handler:
            result = {"ok": False, "error": f"unknown action type: {act_type}"}
        else:
            try:
                result = handler(act)
            except Exception as e:
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if result.get("ok"):
            success_count += 1
        else:
            fail_count += 1

        emit({"idx": idx, "type": act_type, **result})

    # Optional screenshot after batch
    if take_screenshot_after:
        res = action_screenshot({"mode": "1"})
        emit({"idx": len(actions), "type": "screenshot_after", **res})

    emit({"done": True, "total": len(actions), "success": success_count, "failed": fail_count})


if __name__ == "__main__":
    main()
