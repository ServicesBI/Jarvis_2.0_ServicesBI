# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
screen-state.py — Windows desktop state monitor daemon.
Uses Win32 APIs via ctypes (no screenshots) to track open windows,
foreground app, cursor position, and monitor configuration.
Outputs JSON lines to stdout on every state change or heartbeat (2s).
"""

import sys
import os
import json
import time
import argparse
import ctypes
import ctypes.wintypes as wt
from collections import OrderedDict

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Win32 type aliases & constants
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM
)

MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

def get_window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd: int):
    rect = wt.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return [rect.left, rect.top, rect.right, rect.bottom]
    return [0, 0, 0, 0]


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def get_pid(hwnd: int) -> int:
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_process_name(pid: int) -> str:
    """Get process executable name via Win32 (fallback to psutil)."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            size = wt.DWORD(260)
            # QueryFullProcessImageNameW
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            kernel32.CloseHandle(h)
            if ok:
                return os.path.basename(buf.value)
    except Exception:
        pass
    # fallback
    try:
        import psutil
        p = psutil.Process(pid)
        return p.name()
    except Exception:
        return ""


def enum_windows():
    """Return list of visible windows with non-empty titles."""
    results = []

    def _cb(hwnd, _lparam):
        try:
            if not is_visible(hwnd):
                return True
            title = get_window_text(hwnd)
            if not title:
                return True
            pid = get_pid(hwnd)
            proc = get_process_name(pid)
            rect = get_window_rect(hwnd)
            minimized = is_minimized(hwnd)
            results.append(
                OrderedDict(
                    hwnd=hwnd,
                    title=title,
                    proc=proc,
                    pid=pid,
                    rect=rect,
                    min=minimized,
                )
            )
        except Exception:
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return results


def get_foreground_info():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        title = get_window_text(hwnd)
        pid = get_pid(hwnd)
        proc = get_process_name(pid)
        rect = get_window_rect(hwnd)
        return OrderedDict(hwnd=hwnd, title=title, proc=proc, pid=pid, rect=rect)
    except Exception:
        return None


def get_cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return [pt.x, pt.y]


def get_monitors():
    monitors = []

    def _cb(hmon, hdc, lprect, lparam):
        try:
            mi = type(
                "MONITORINFOEX",
                (ctypes.Structure,),
                {
                    "_fields_": [
                        ("cbSize", wt.DWORD),
                        ("rcMonitor", wt.RECT),
                        ("rcWork", wt.RECT),
                        ("dwFlags", wt.DWORD),
                        ("szDevice", ctypes.c_wchar * 32),
                    ]
                },
            )()
            mi.cbSize = ctypes.sizeof(mi)
            user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
            r = mi.rcMonitor
            monitors.append(
                OrderedDict(
                    idx=len(monitors),
                    x=r.left,
                    y=r.top,
                    w=r.right - r.left,
                    h=r.bottom - r.top,
                    primary=bool(mi.dwFlags & 1),
                )
            )
        except Exception:
            pass
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    return monitors


# ---------------------------------------------------------------------------
# Snapshot & diff
# ---------------------------------------------------------------------------

def take_snapshot():
    fg = get_foreground_info()
    windows = enum_windows()
    monitors = get_monitors()
    cursor = get_cursor_pos()
    return OrderedDict(
        ts=int(time.time()),
        fg=fg,
        windows=windows,
        monitors=monitors,
        cursor=cursor,
    )


def snapshot_fingerprint(snap):
    """Quick fingerprint to detect changes (ignores cursor jitter < 5px)."""
    fg_id = snap["fg"]["hwnd"] if snap["fg"] else 0
    fg_title = snap["fg"]["title"] if snap["fg"] else ""
    win_ids = tuple((w["hwnd"], w["title"], w["min"]) for w in snap["windows"])
    # quantize cursor to 5px grid to avoid spamming on micro-moves
    cx = snap["cursor"][0] // 5
    cy = snap["cursor"][1] // 5
    return (fg_id, fg_title, win_ids, cx, cy)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Windows desktop state monitor")
    parser.add_argument(
        "--mode",
        choices=["stdout", "file"],
        default="stdout",
        help="Output mode: stdout (JSON lines) or file (write to system/_screen_state.json)",
    )
    args = parser.parse_args()

    file_path = None
    if args.mode == "file":
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_screen_state.json")

    prev_fp = None
    last_output_time = 0.0
    heartbeat_interval = 2.0
    poll_interval = 0.2

    while True:
        try:
            snap = take_snapshot()
            fp = snapshot_fingerprint(snap)
            now = time.monotonic()

            changed = fp != prev_fp
            heartbeat_due = (now - last_output_time) >= heartbeat_interval

            if changed or heartbeat_due:
                snap["ts"] = int(time.time())
                line = json.dumps(snap, ensure_ascii=False)

                if args.mode == "file" and file_path:
                    try:
                        tmp = file_path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            f.write(line)
                        os.replace(tmp, file_path)
                    except Exception:
                        pass
                else:
                    print(line)
                    sys.stdout.flush()

                prev_fp = fp
                last_output_time = now

        except KeyboardInterrupt:
            break
        except UnicodeDecodeError:
            # Skip frames with encoding issues in window titles
            pass
        except Exception:
            # Silently skip transient errors (window handles going stale, etc.)
            pass

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
