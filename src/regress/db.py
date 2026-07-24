"""SQLAlchemy engine/session setup.

SQLite by default (zero-config), Postgres via REGRESS_DB_URL for scale,
per the design north star in CLAUDE.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from regress.models import Base

DEFAULT_DB_URL = "sqlite:///regress.db"


def _make_engine(db_url: str | None = None) -> Engine:
    url = db_url or os.environ.get("REGRESS_DB_URL", DEFAULT_DB_URL)
    if not url.startswith("sqlite"):
        return create_engine(url)
    if ":memory:" in url:
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, connect_args={"check_same_thread": False})


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db(bind: Engine | None = None) -> None:
    Base.metadata.create_all(bind=bind or engine)


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
