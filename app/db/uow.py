"""Fronteira transacional mínima: commit no sucesso, rollback na exceção.

Existe apenas para provar que Task + AgentRun podem ser criados atomicamente
quando dois repositories compartilham a mesma Session. Não é usado pelo
runtime nesta fase.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def unit_of_work(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
