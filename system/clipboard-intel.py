# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
JARVIS Clipboard Intelligence Daemon
Monitors Windows clipboard changes and analyzes content in real-time.
Outputs JSON lines to stdout with content classification and suggestions.
"""

import ctypes
import ctypes.wintypes as wintypes
import sys
import json
import re
import time
import signal

# ---------- stdout utf-8 ----------
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ---------- Win32 clipboard API ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13

OpenClipboard = user32.OpenClipboard
OpenClipboard.argtypes = [wintypes.HWND]
OpenClipboard.restype = wintypes.BOOL

CloseClipboard = user32.CloseClipboard
CloseClipboard.argtypes = []
CloseClipboard.restype = wintypes.BOOL

GetClipboardData = user32.GetClipboardData
GetClipboardData.argtypes = [wintypes.UINT]
GetClipboardData.restype = wintypes.HANDLE

GetClipboardSequenceNumber = user32.GetClipboardSequenceNumber
GetClipboardSequenceNumber.argtypes = []
GetClipboardSequenceNumber.restype = wintypes.DWORD

GlobalLock = kernel32.GlobalLock
GlobalLock.argtypes = [wintypes.HANDLE]
GlobalLock.restype = ctypes.c_void_p

GlobalUnlock = kernel32.GlobalUnlock
GlobalUnlock.argtypes = [wintypes.HANDLE]
GlobalUnlock.restype = wintypes.BOOL

# ---------- Patterns ----------
RE_URL = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+\.[a-z]{2,}[^\s<>\"']*",
    re.IGNORECASE,
)
RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
RE_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,3}\)?[\s\-]?\d{4,5}[\s\-]?\d{4}"
)
RE_ADDRESS = re.compile(
    r"(?:Rua|Av\.?|Avenida|Alameda|Travessa|Praça|Estrada|Rod\.?|Rodovia|Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?)"
    r"\s+.{5,}",
    re.IGNORECASE,
)
RE_CURRENCY = re.compile(
    r"(?:R\$|US\$|\$|EUR|€|£)\s*[\d.,]+|[\d.,]+\s*(?:reais|dollars|euros|pounds)",
    re.IGNORECASE,
)
RE_NUMBER = re.compile(r"^[\s]*[\-+]?[\d.,]+[\s]*$")
RE_JSON = re.compile(r"^\s*[\[{]")
RE_CODE_HINTS = re.compile(
    r"(?:def |class |function |const |let |var |import |from |#include|public |private |void |int |return |\{.*\}|=>|\.map\(|\.filter\(|console\.log|print\(|System\.out)",
    re.MULTILINE,
)

# Code language detection hints
LANG_HINTS = {
    "python": re.compile(r"(?:def |import |from .+ import|print\(|class .+:)", re.M),
    "javascript": re.compile(r"(?:const |let |var |=>|console\.|require\(|module\.exports)", re.M),
    "typescript": re.compile(r"(?:interface |type |:\s*(?:string|number|boolean))", re.M),
    "java": re.compile(r"(?:public class|System\.out|private |protected )", re.M),
    "c": re.compile(r"(?:#include|printf\(|int main|void |malloc)", re.M),
    "cpp": re.compile(r"(?:std::|cout|cin|#include <iostream>|namespace)", re.M),
    "csharp": re.compile(r"(?:using System|namespace |Console\.Write)", re.M),
    "html": re.compile(r"(?:<html|<div|<span|<body|<!DOCTYPE)", re.IGNORECASE | re.M),
    "css": re.compile(r"(?:\{[^}]*(?:color|margin|padding|display)\s*:)", re.M),
    "sql": re.compile(r"(?:SELECT |INSERT |UPDATE |DELETE |CREATE TABLE|ALTER TABLE)", re.IGNORECASE | re.M),
    "bash": re.compile(r"(?:#!/bin/|echo |grep |awk |sed |chmod )", re.M),
    "rust": re.compile(r"(?:fn |let mut |impl |pub fn |use std::)", re.M),
    "go": re.compile(r"(?:func |package |import \(|fmt\.Print)", re.M),
}

# Foreign language: detect primarily-English text (for a PT-BR user)
RE_ENGLISH = re.compile(r"\b(?:the|is|are|was|were|have|has|been|will|would|could|should|with|that|this|from|they|their|about|which|when|there|been|into|more|than|also|just|only|very|much|such|even|most|some|other|after|before|between|because|through|during|without)\b", re.IGNORECASE)


def get_clipboard_text() -> str | None:
    """Read current clipboard text via Win32 API."""
    if not OpenClipboard(None):
        return None
    try:
        handle = GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            GlobalUnlock(handle)
    finally:
        CloseClipboard()


def detect_language(text: str) -> str | None:
    """Detect code language from content."""
    for lang, pattern in LANG_HINTS.items():
        if pattern.search(text):
            return lang
    return None


def analyze(text: str) -> dict:
    """Classify clipboard content and return analysis dict."""
    stripped = text.strip()

    # 1. URL
    m = RE_URL.search(stripped)
    if m and len(stripped) < 2048:
        return {"type": "url", "content": m.group(), "suggest": "open_browser"}

    # 2. Email
    m = RE_EMAIL.search(stripped)
    if m and len(stripped) < 200:
        return {"type": "email", "content": m.group(), "suggest": "send_email"}

    # 3. Phone
    m = RE_PHONE.search(stripped)
    if m and len(stripped) < 50:
        return {"type": "phone", "content": m.group().strip(), "suggest": "call"}

    # 4. Address
    m = RE_ADDRESS.search(stripped)
    if m and len(stripped) < 300:
        return {"type": "address", "content": stripped, "suggest": "open_maps"}

    # 5. JSON / structured data
    if RE_JSON.match(stripped):
        try:
            json.loads(stripped)
            return {"type": "data", "format": "json", "content": stripped[:500], "suggest": "format"}
        except (json.JSONDecodeError, ValueError):
            pass

    # 6. Code snippet
    if RE_CODE_HINTS.search(stripped):
        lang = detect_language(stripped) or "unknown"
        return {"type": "code", "lang": lang, "content": stripped[:500], "suggest": "run_or_explain"}

    # 7. Currency / number
    m = RE_CURRENCY.search(stripped)
    if m:
        return {"type": "number", "content": m.group().strip(), "suggest": "calculate"}

    if RE_NUMBER.match(stripped):
        return {"type": "number", "content": stripped.strip(), "suggest": "calculate"}

    # 8. English text (foreign for PT-BR user)
    words = stripped.split()
    if len(words) >= 5:
        english_hits = len(RE_ENGLISH.findall(stripped))
        ratio = english_hits / len(words)
        if ratio > 0.15:
            return {"type": "foreign_text", "lang": "en", "content": stripped[:500], "suggest": "translate"}

    # 9. Plain text fallback
    return {"type": "text", "content": stripped[:500], "word_count": len(words)}


def build_output(text: str, analysis: dict) -> dict:
    """Build the JSON output line."""
    preview = text[:200].replace("\n", " ").strip()
    return {
        "ts": int(time.time()),
        "clipboard": text[:1000],
        "analysis": analysis,
        "preview": preview,
    }


def emit(data: dict):
    """Write a JSON line to stdout and flush."""
    try:
        sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def main():
    """Main daemon loop: poll clipboard every 500ms."""
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    last_seq = GetClipboardSequenceNumber()

    # Startup beacon
    emit({
        "ts": int(time.time()),
        "event": "daemon_start",
        "message": "Clipboard Intelligence daemon started",
    })

    while running:
        try:
            seq = GetClipboardSequenceNumber()
            if seq != last_seq:
                last_seq = seq
                text = get_clipboard_text()
                if text and text.strip():
                    analysis = analyze(text)
                    output = build_output(text, analysis)
                    emit(output)
        except UnicodeDecodeError as e:
            emit({
                "ts": int(time.time()),
                "event": "encoding_error",
                "message": f"Clipboard encoding issue: {e}",
            })
        except Exception as e:
            emit({
                "ts": int(time.time()),
                "event": "error",
                "message": str(e),
            })

        time.sleep(0.5)

    emit({
        "ts": int(time.time()),
        "event": "daemon_stop",
        "message": "Clipboard Intelligence daemon stopped",
    })


if __name__ == "__main__":
    main()
