"""Ponto de entrada local do backend FastAPI do Jarvis."""

from __future__ import annotations

import sys

import uvicorn

from app.core.config import HOST, PORT
from app.core.startup_guard import StartupDecision, run_preflight
from app.main import app


def main() -> int:
    """Inicia uma unica instancia do FastAPI no endereco local configurado.

    Faz preflight antes de tentar o bind: se ja houver um Jarvis saudavel em
    HOST:PORT, nao inicia uma segunda instancia (evita WinError 10048). Se a
    porta estiver ocupada por outro processo, nunca o encerra automaticamente.
    """

    preflight = run_preflight(HOST, PORT)

    if preflight.decision is StartupDecision.ALREADY_RUNNING:
        print("Jarvis ja esta em execucao.", flush=True)
        print(f"Endereco: http://{HOST}:{PORT}", flush=True)
        print("Nenhuma nova instancia foi iniciada.", flush=True)
        return 0

    if preflight.decision is StartupDecision.PORT_OCCUPIED:
        print("Nao foi possivel iniciar o Jarvis.", flush=True)
        print(f"A porta {PORT} esta ocupada por outro processo.", flush=True)
        print("Nenhum processo foi encerrado automaticamente.", flush=True)
        print(f"Detalhe: {preflight.detail}.", flush=True)
        return 1

    print("Jarvis iniciado", flush=True)
    print(f"Endereco: http://{HOST}:{PORT}", flush=True)
    print(f"Porta: {PORT}", flush=True)
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        reload=False,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    app.state.jarvis_shutdown_requested = False

    try:
        server.run()
    except OSError as exc:
        print("Nao foi possivel iniciar o Jarvis.", flush=True)
        print(f"A porta {PORT} foi ocupada por outro processo durante o startup.", flush=True)
        print(f"Detalhe: {exc}", flush=True)
        return 1
    finally:
        app.state.uvicorn_server = None

    return 0


if __name__ == "__main__":
    sys.exit(main())
