"""
JARVIS Workflow Recording & Replay System
Records sequences of keyboard/mouse actions and replays them as automated workflows.
Uses low-level Windows hooks via ctypes for recording, pyautogui for replay.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import time
import argparse
import ctypes
import ctypes.wintypes
import threading
import signal
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKFLOWS_DIR = Path(__file__).parent / "workflows"
WORKFLOWS_DIR.mkdir(exist_ok=True)

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A

# Virtual key codes
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_RETURN = 0x0D
VK_BACK = 0x08
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_DELETE = 0x2E
VK_CAPITAL = 0x14

MODIFIER_VKS = {VK_SHIFT, VK_CONTROL, VK_MENU, VK_LSHIFT, VK_RSHIFT,
                VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU}

# Friendly names for special keys
VK_NAMES = {
    0x0D: "enter", 0x08: "backspace", 0x09: "tab", 0x1B: "escape",
    0x20: "space", 0x2E: "delete", 0x2D: "insert", 0x24: "home",
    0x23: "end", 0x21: "pageup", 0x22: "pagedown",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5",
    0x75: "f6", 0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10",
    0x7A: "f11", 0x7B: "f12", 0x91: "scrolllock", 0x90: "numlock",
    0x2C: "printscreen", 0x13: "pause",
}

# ctypes structures
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_foreground_window_title() -> str:
    """Return the title of the current foreground window."""
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def focus_window_by_title(partial_title: str) -> bool:
    """Try to find and focus a window whose title contains *partial_title*."""
    result = {"hwnd": None}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if partial_title.lower() in buf.value.lower():
                if user32.IsWindowVisible(hwnd):
                    result["hwnd"] = hwnd
                    return False  # stop enumeration
        return True

    user32.EnumWindows(enum_cb, 0)
    if result["hwnd"]:
        user32.SetForegroundWindow(result["hwnd"])
        time.sleep(0.3)
        return True
    return False


def format_duration(ms: int) -> str:
    """Pretty-print a millisecond duration."""
    secs = ms / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    mins = int(secs // 60)
    secs = secs % 60
    return f"{mins}m {secs:.0f}s"


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------

class WorkflowRecorder:
    """Low-level keyboard & mouse recorder using Windows hooks."""

    def __init__(self, name: str):
        self.name = name
        self.actions: list[dict] = []
        self.start_time: float = 0
        self._running = False

        # Modifier state tracking
        self._ctrl = False
        self._shift = False
        self._alt = False

        # Text accumulation (to collapse individual keystrokes into "type" actions)
        self._text_buf: list[str] = []
        self._text_start_t: int = 0

        # Hook handles (prevent GC)
        self._kb_hook = None
        self._mouse_hook = None
        self._kb_proc = None
        self._mouse_proc = None

    # -- helpers --

    def _elapsed(self) -> int:
        return int((time.perf_counter() - self.start_time) * 1000)

    def _flush_text(self):
        """Collapse buffered keystrokes into a single 'type' action."""
        if self._text_buf:
            text = "".join(self._text_buf)
            self.actions.append({
                "t": self._text_start_t,
                "type": "type",
                "text": text,
            })
            self._text_buf.clear()

    # -- hook callbacks --

    def _kb_callback(self, nCode, wParam, lParam):
        if nCode >= 0 and self._running:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode

            is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)

            # Track modifier state
            if vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                self._ctrl = is_down
            elif vk in (VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
                self._shift = is_down
            elif vk in (VK_MENU, VK_LMENU, VK_RMENU):
                self._alt = is_down

            if is_down and vk not in MODIFIER_VKS:
                t = self._elapsed()

                # If any modifier held -> emit as hotkey
                if self._ctrl or self._alt:
                    self._flush_text()
                    parts = []
                    if self._ctrl:
                        parts.append("ctrl")
                    if self._alt:
                        parts.append("alt")
                    if self._shift:
                        parts.append("shift")
                    key_name = VK_NAMES.get(vk) or chr(vk).lower()
                    parts.append(key_name)
                    combo = "+".join(parts)
                    self.actions.append({
                        "t": t,
                        "type": "key",
                        "keys": combo,
                        "window": get_foreground_window_title(),
                    })
                elif vk in VK_NAMES:
                    # Special key without modifier
                    self._flush_text()
                    self.actions.append({
                        "t": t,
                        "type": "key",
                        "keys": VK_NAMES[vk],
                        "window": get_foreground_window_title(),
                    })
                else:
                    # Regular printable character -> accumulate into text buffer
                    # Use ToUnicodeEx to get the actual character
                    kb_state = (ctypes.c_ubyte * 256)()
                    user32.GetKeyboardState(kb_state)
                    buf = (ctypes.c_wchar * 5)()
                    ret = user32.ToUnicodeEx(
                        vk, kb.scanCode, kb_state, buf, 5, 0,
                        user32.GetKeyboardLayout(0),
                    )
                    if ret > 0:
                        ch = buf[0]
                        if not self._text_buf:
                            self._text_start_t = t
                        self._text_buf.append(ch)

        return user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

    def _mouse_callback(self, nCode, wParam, lParam):
        if nCode >= 0 and self._running:
            ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents

            if wParam == WM_LBUTTONDOWN:
                self._flush_text()
                self.actions.append({
                    "t": self._elapsed(),
                    "type": "click",
                    "x": ms.pt.x,
                    "y": ms.pt.y,
                    "button": "left",
                    "window": get_foreground_window_title(),
                })
            elif wParam == WM_RBUTTONDOWN:
                self._flush_text()
                self.actions.append({
                    "t": self._elapsed(),
                    "type": "click",
                    "x": ms.pt.x,
                    "y": ms.pt.y,
                    "button": "right",
                    "window": get_foreground_window_title(),
                })
            elif wParam == WM_MBUTTONDOWN:
                self._flush_text()
                self.actions.append({
                    "t": self._elapsed(),
                    "type": "click",
                    "x": ms.pt.x,
                    "y": ms.pt.y,
                    "button": "middle",
                    "window": get_foreground_window_title(),
                })
            elif wParam == WM_MOUSEWHEEL:
                self._flush_text()
                # mouseData high word = wheel delta (positive = up)
                delta = ctypes.c_short(ms.mouseData >> 16).value
                direction = "up" if delta > 0 else "down"
                clicks = abs(delta) // 120
                self.actions.append({
                    "t": self._elapsed(),
                    "type": "scroll",
                    "x": ms.pt.x,
                    "y": ms.pt.y,
                    "direction": direction,
                    "clicks": max(clicks, 1),
                    "window": get_foreground_window_title(),
                })

        return user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)

    # -- public API --

    def start(self):
        """Install hooks and pump messages until stopped."""
        self._running = True
        self.start_time = time.perf_counter()

        # Record initial window focus
        title = get_foreground_window_title()
        if title:
            self.actions.append({"t": 0, "type": "app_focus", "window": title})

        # Create C-callable procs (prevent GC)
        self._kb_proc = HOOKPROC(self._kb_callback)
        self._mouse_proc = HOOKPROC(self._mouse_callback)

        self._kb_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kb_proc, kernel32.GetModuleHandleW(None), 0
        )
        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, kernel32.GetModuleHandleW(None), 0
        )

        if not self._kb_hook or not self._mouse_hook:
            raise RuntimeError("Failed to install hooks")

        print(f"[JARVIS] Recording workflow '{self.name}' ...")
        print("[JARVIS] Press Ctrl+C to stop recording.\n")

        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        """Unhook and save the workflow."""
        self._running = False
        self._flush_text()

        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None

        # Post quit to unblock GetMessageW
        user32.PostThreadMessageW(
            kernel32.GetCurrentThreadId(), 0x0012, 0, 0  # WM_QUIT
        )

        self._save()

    def _save(self):
        duration = self._elapsed() if self.start_time else 0
        workflow = {
            "name": self.name,
            "recorded": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration,
            "action_count": len(self.actions),
            "actions": self.actions,
        }
        path = WORKFLOWS_DIR / f"{self.name}.json"
        path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[JARVIS] Saved workflow '{self.name}' -> {path}")
        print(f"         Actions: {len(self.actions)}  |  Duration: {format_duration(duration)}")


# ---------------------------------------------------------------------------
# Replayer
# ---------------------------------------------------------------------------

class WorkflowReplayer:
    """Replays a recorded workflow using pyautogui."""

    def __init__(self, workflow: dict, speed: float = 1.0, dry_run: bool = False):
        self.workflow = workflow
        self.speed = speed
        self.dry_run = dry_run
        self.actions = workflow["actions"]

    def replay(self):
        try:
            import pyautogui
        except ImportError:
            print("[JARVIS] ERROR: pyautogui is required for replay.")
            print("         Install with: pip install pyautogui")
            sys.exit(1)

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.02

        name = self.workflow["name"]
        total = len(self.actions)
        mode = "DRY RUN" if self.dry_run else "LIVE"
        print(f"[JARVIS] Replaying '{name}' ({total} actions) [{mode}] speed={self.speed}x")
        print()

        prev_t = 0
        for i, action in enumerate(self.actions, 1):
            t = action["t"]
            atype = action["type"]

            # Wait for correct timing
            delay = max(0, (t - prev_t) / 1000 / self.speed)
            if delay > 0 and not self.dry_run:
                time.sleep(delay)
            prev_t = t

            # Window verification
            expected_win = action.get("window")
            if expected_win and not self.dry_run:
                current = get_foreground_window_title()
                if expected_win.lower() not in current.lower():
                    print(f"  [{i}/{total}] Window mismatch: expected '{expected_win}', got '{current}'")
                    if not focus_window_by_title(expected_win):
                        print(f"           Could not find window '{expected_win}', continuing anyway...")
                    else:
                        print(f"           Focused '{expected_win}'")
                        time.sleep(0.2)

            # Describe action
            desc = self._describe(action)
            tag = "SKIP" if self.dry_run else "EXEC"
            print(f"  [{i}/{total}] +{t}ms  {tag}: {desc}")

            if self.dry_run:
                continue

            # Execute
            if atype == "app_focus":
                focus_window_by_title(action["window"])

            elif atype == "click":
                btn = action.get("button", "left")
                pyautogui.click(action["x"], action["y"], button=btn)

            elif atype == "type":
                pyautogui.typewrite(action["text"], interval=0.02) if action["text"].isascii() else pyautogui.write(action["text"])

            elif atype == "key":
                keys = action["keys"]
                pyautogui.hotkey(*keys.split("+"))

            elif atype == "scroll":
                clicks = action.get("clicks", 3)
                direction = action.get("direction", "down")
                amount = clicks if direction == "up" else -clicks
                pyautogui.scroll(amount, x=action.get("x"), y=action.get("y"))

        print(f"\n[JARVIS] Replay complete.")

    @staticmethod
    def _describe(action: dict) -> str:
        atype = action["type"]
        if atype == "app_focus":
            return f"Focus window: {action['window']}"
        elif atype == "click":
            btn = action.get("button", "left")
            return f"{btn}-click ({action['x']}, {action['y']}) on '{action.get('window', '?')}'"
        elif atype == "type":
            text = action["text"]
            display = text if len(text) <= 40 else text[:37] + "..."
            return f"Type: \"{display}\""
        elif atype == "key":
            return f"Key: {action['keys']}"
        elif atype == "scroll":
            return f"Scroll {action.get('direction', 'down')} x{action.get('clicks', 3)}"
        else:
            return f"Unknown action: {atype}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_record(args):
    recorder = WorkflowRecorder(args.name)

    def on_signal(*_):
        recorder.stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGBREAK, on_signal)

    recorder.start()


def cmd_replay(args):
    path = WORKFLOWS_DIR / f"{args.name}.json"
    if not path.exists():
        print(f"[JARVIS] Workflow '{args.name}' not found at {path}")
        sys.exit(1)

    workflow = json.loads(path.read_text(encoding="utf-8"))

    # Update last-used timestamp
    workflow["last_used"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")

    replayer = WorkflowReplayer(workflow, speed=args.speed, dry_run=args.dry_run)
    replayer.replay()


def cmd_stop(_args):
    """Signal a running recorder to stop (posts WM_QUIT to all console processes)."""
    print("[JARVIS] To stop recording, press Ctrl+C in the recorder window.")


def cmd_list(_args):
    files = sorted(WORKFLOWS_DIR.glob("*.json"))
    if not files:
        print("[JARVIS] No saved workflows.")
        return

    print(f"[JARVIS] Saved workflows ({len(files)}):\n")
    print(f"  {'Name':<25} {'Actions':>8} {'Duration':>10} {'Last Used':<20}")
    print(f"  {'─' * 25} {'─' * 8} {'─' * 10} {'─' * 20}")

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            name = data.get("name", f.stem)
            count = data.get("action_count", len(data.get("actions", [])))
            dur = format_duration(data.get("duration_ms", 0))
            last = data.get("last_used", data.get("recorded", "never"))
            if last != "never":
                last = last[:19].replace("T", " ")
            print(f"  {name:<25} {count:>8} {dur:>10} {last:<20}")
        except (json.JSONDecodeError, KeyError):
            print(f"  {f.stem:<25} {'(corrupt)':>8}")

    print()


def main():
    parser = argparse.ArgumentParser(
        prog="workflow-recorder",
        description="JARVIS Workflow Recording & Replay System",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # record
    p_rec = sub.add_parser("record", help="Start recording a workflow")
    p_rec.add_argument("name", help="Workflow name (used as filename)")
    p_rec.set_defaults(func=cmd_record)

    # stop
    p_stop = sub.add_parser("stop", help="Stop active recording")
    p_stop.set_defaults(func=cmd_stop)

    # replay
    p_rep = sub.add_parser("replay", help="Replay a saved workflow")
    p_rep.add_argument("name", help="Workflow name to replay")
    p_rep.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier (default: 1.0)")
    p_rep.add_argument("--dry-run", action="store_true", help="Show actions without executing")
    p_rep.set_defaults(func=cmd_replay)

    # list
    p_list = sub.add_parser("list", help="List all saved workflows")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
