"""Engine/session PostgreSQL do Jarvis.

Sem fallback silencioso: a ausência de `JARVIS_DATABASE_URL` só produz erro
quando alguém de fato tenta instanciar o banco (`create_database_engine`),
nunca na inicialização do restante do runtime.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_setting


class DatabaseNotConfiguredError(RuntimeError):
    """`JARVIS_DATABASE_URL` não está configurada."""


def create_database_engine(url: str | None = None) -> Engine:
    """Cria o Engine PostgreSQL. Nunca cai para SQLite."""

    resolved = url or get_setting("JARVIS_DATABASE_URL")
    if not resolved:
        raise DatabaseNotConfiguredError(
            "JARVIS_DATABASE_URL não configurada; o banco de dados do Jarvis "
            "não pode ser instanciado."
        )
    if resolved.startswith("sqlite"):
        raise ValueError(
            "SQLite não é suportado como banco do Jarvis, nem como fallback."
        )
    return create_engine(resolved, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
