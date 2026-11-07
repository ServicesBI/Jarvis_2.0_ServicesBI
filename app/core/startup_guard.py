"""Preflight idempotente de startup do backend Jarvis (host:porta oficiais).

Evita duas falhas conhecidas ao iniciar `run.py` no Windows:
- WinError 10048 quando uma instancia saudavel do proprio Jarvis ja ocupa a porta;
- encerramento indevido de processos nao comprovados como Jarvis.

Porta ocupada nao prova que e o Jarvis: a identidade so e confirmada pelo
contrato real de `/api/health` (app/api/health.py), nunca apenas por bind/connect.
"""

from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass
from enum import Enum

import httpx

HEALTH_TIMEOUT_SECONDS = 2.0
PORT_OWNER_LOOKUP_TIMEOUT_SECONDS = 3.0

_LISTENER_LINE = re.compile(
    r"^\s*TCP\s+\S+:(?P<port>\d+)\s+\S+\s+LISTENING\s+(?P<pid>\d+)\s*$",
    re.MULTILINE,
)


class StartupDecision(Enum):
    """Resultado do preflight: o que run.py deve fazer a seguir."""

    START = "start"
    ALREADY_RUNNING = "already_running"
    PORT_OCCUPIED = "port_occupied"


@dataclass(frozen=True)
class PreflightResult:
    decision: StartupDecision
    detail: str


def is_jarvis_health_payload(payload: object) -> bool:
    """Confirma o contrato real de /api/health (app/api/health.py)."""

    if not isinstance(payload, dict):
        return False
    components = payload.get("components")
    if not isinstance(components, dict):
        return False
    server = components.get("server")
    return isinstance(server, dict) and server.get("status") == "ok"


def probe_jarvis_health(host: str, port: int, timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    """Verifica, com timeout curto, se host:port responde como Jarvis FastAPI."""

    try:
        response = httpx.get(f"http://{host}:{port}/api/health", timeout=timeout)
    except httpx.HTTPError:
        return False

    if response.status_code != 200:
        return False

    try:
        payload = response.json()
    except ValueError:
        return False

    return is_jarvis_health_payload(payload)


def _port_is_free(host: str, port: int) -> bool:
    """Prova autoritativa: tenta o mesmo bind() que o uvicorn faria."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _process_name(pid: int) -> str | None:
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        return None


def describe_port_owner(port: int) -> str:
    """Melhor esforco, somente leitura, para identificar quem ocupa a porta."""

    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=PORT_OWNER_LOOKUP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "processo desconhecido"

    for match in _LISTENER_LINE.finditer(completed.stdout):
        if int(match.group("port")) != port:
            continue
        pid = match.group("pid")
        name = _process_name(int(pid))
        return f"PID {pid} ({name})" if name else f"PID {pid}"

    return "processo desconhecido"


def run_preflight(host: str, port: int) -> PreflightResult:
    """Decide com seguranca o que fazer antes de iniciar o Uvicorn.

    Nunca encerra nem altera processos: apenas le o estado da porta e do
    endpoint de saude para produzir uma decisao.
    """

    if _port_is_free(host, port):
        return PreflightResult(StartupDecision.START, "porta livre")

    if probe_jarvis_health(host, port):
        return PreflightResult(
            StartupDecision.ALREADY_RUNNING,
            f"Jarvis ja esta em execucao em http://{host}:{port}",
        )

    owner = describe_port_owner(port)
    return PreflightResult(
        StartupDecision.PORT_OCCUPIED,
        f"a porta {port} esta ocupada por outro processo ({owner})",
    )
