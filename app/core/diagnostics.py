"""Coleta segura das informações usadas pelas rotas de diagnóstico."""

from __future__ import annotations

import os
import platform
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_setting as _local_env_value
_STARTED_AT_NS = time.monotonic_ns()
_STARTED_AT = datetime.now(timezone.utc).isoformat()
def get_session_stats() -> dict[str, object]:
    """Replica o envelope de /api/stats para esta sessão Python."""

    uptime_ms = max(0, (time.monotonic_ns() - _STARTED_AT_NS) // 1_000_000)
    return {
        "uptime": uptime_ms,
        "uptime_seconds": uptime_ms // 1000,
        "started_at": _STARTED_AT,
        "tokensIn": 0,
        "tokensOut": 0,
        "tokens": 0,
        "requests": 0,
        "plan": _local_env_value("CLAUDE_PLAN") or "Max",
        "lastLatency": 0,
        "pool": {"opus": 0, "sonnet": 0, "haiku": 0},
    }


def _empty_system_stats(source: str) -> dict[str, object]:
    return {
        "cpu": {
            "name": platform.processor() or None,
            "usage": None,
            "temp": None,
            "cores": os.cpu_count() or 0,
        },
        "gpu": {"name": None, "temp": None, "vram": None, "usage": None},
        "ram": {"usage": None, "total": 0, "free": 0, "type": None},
        "source": source,
    }


def _first_temperature(psutil_module: Any) -> int | None:
    try:
        temperature_groups = psutil_module.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for entries in temperature_groups.values():
        if entries:
            current = getattr(entries[0], "current", None)
            return round(current) if current is not None else None
    return None


def collect_system_stats() -> dict[str, object]:
    """Coleta CPU/RAM com psutil quando disponível e degrada sem falhar."""

    try:
        import psutil  # Dependência já declarada, mas opcional durante a inicialização.
    except ImportError:
        return _empty_system_stats("python-only")

    try:
        memory = psutil.virtual_memory()
        raw_total_gb = memory.total / (1024**3)
        rounded_total_gb = int(round(raw_total_gb / 8) * 8) or round(raw_total_gb)
        return {
            "cpu": {
                "name": platform.processor() or None,
                "usage": round(psutil.cpu_percent(interval=0.1)),
                "temp": _first_temperature(psutil),
                "cores": psutil.cpu_count(logical=True) or 0,
            },
            "gpu": {"name": None, "temp": None, "vram": None, "usage": None},
            "ram": {
                "usage": round(memory.percent),
                "total": rounded_total_gb,
                "free": round(memory.available / (1024**3)),
                "type": None,
            },
            "source": "psutil",
        }
    except Exception:
        return _empty_system_stats("error")


def get_local_service_health() -> dict[str, object]:
    """Retorna API e voz sem executar ou detectar providers."""
    openai_configured = bool((_local_env_value("OPENAI_API_KEY") or "").strip())
    return {
        "server": "ok",
        "api": {
            "status": "ok" if openai_configured else "error",
            "detail": "OpenAI API configurada" if openai_configured else "OPENAI_API_KEY nao configurada",
        },
        "voice": {
            "status": "ok" if openai_configured else "error",
            "detail": (
                "Servicos de voz disponiveis"
                if openai_configured
                else "Servicos de voz indisponiveis sem OPENAI_API_KEY"
            ),
        },
    }
