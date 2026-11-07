"""Roda comandos Alembic programaticamente contra uma URL explícita.

`alembic/env.py` lê a URL via `app.core.config.get_setting("JARVIS_DATABASE_URL")`
(nunca via `configparser`, que quebra com senhas percent-encoded). Este módulo
troca essa variável de ambiente só durante a chamada, sempre restaurando o
valor anterior — nunca grava em `.env`, nunca deixa a URL vazar para outro
código depois de retornar.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"


@contextmanager
def _database_url_env(database_url: str) -> Iterator[None]:
    previous = os.environ.get("JARVIS_DATABASE_URL")
    os.environ["JARVIS_DATABASE_URL"] = database_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("JARVIS_DATABASE_URL", None)
        else:
            os.environ["JARVIS_DATABASE_URL"] = previous


def _config() -> Config:
    return Config(str(_ALEMBIC_INI))


def upgrade_to_head(database_url: str) -> None:
    with _database_url_env(database_url):
        command.upgrade(_config(), "head")


def current_revision(database_url: str) -> None:
    with _database_url_env(database_url):
        command.current(_config())


def heads() -> None:
    command.heads(_config())
