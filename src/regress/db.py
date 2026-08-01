"""SQLAlchemy engine/session setup.

SQLite by default (zero-config), Postgres via REGRESS_DB_URL for scale,
per the design north star in CLAUDE.md.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from regress.models import Base

DEFAULT_DB_URL = "sqlite:///regress.db"


def _enable_sqlite_wal(dbapi_connection: Any, _record: Any) -> None:
    """Put file-backed SQLite into WAL mode on every new connection.

    The default rollback journal takes a database-wide write lock, so the
    dashboard's reads stall whenever ingest is writing — exactly the
    contention a live collector hits. WAL lets readers and one writer run
    concurrently; `synchronous=NORMAL` is the standard, durable-enough
    pairing for WAL. Skipped for `:memory:` (WAL is meaningless there) and
    for non-SQLite backends (this listener is only attached to SQLite
    engines).
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _make_engine(db_url: str | None = None) -> Engine:
    url = db_url or os.environ.get("REGRESS_DB_URL", DEFAULT_DB_URL)
    if not url.startswith("sqlite"):
        return create_engine(url)
    if ":memory:" in url:
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_sqlite_wal)
    return engine


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
