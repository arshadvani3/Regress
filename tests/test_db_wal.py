from pathlib import Path

from sqlalchemy import text

from regress.db import _make_engine


def _journal_mode(engine: object) -> str:
    with engine.connect() as conn:  # type: ignore[attr-defined]
        return conn.execute(text("PRAGMA journal_mode")).scalar_one()


def test_file_sqlite_uses_wal(tmp_path: Path) -> None:
    engine = _make_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        assert _journal_mode(engine).lower() == "wal"
    finally:
        engine.dispose()


def test_file_sqlite_sets_synchronous_normal(tmp_path: Path) -> None:
    engine = _make_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        with engine.connect() as conn:
            # NORMAL == 1 in the pragma's integer encoding
            assert conn.execute(text("PRAGMA synchronous")).scalar_one() == 1
    finally:
        engine.dispose()


def test_memory_sqlite_is_not_wal() -> None:
    # In-memory DBs can't use WAL and must not have the listener applied.
    engine = _make_engine("sqlite:///:memory:")
    try:
        assert _journal_mode(engine).lower() == "memory"
    finally:
        engine.dispose()


def test_reads_work_while_a_write_transaction_is_open(tmp_path: Path) -> None:
    """The whole point of WAL: a reader isn't blocked by an open writer."""
    engine = _make_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
            conn.commit()

        writer = engine.connect()
        writer.execute(text("BEGIN"))
        writer.execute(text("INSERT INTO t (v) VALUES ('pending')"))
        # writer transaction is still open (uncommitted) here

        reader = engine.connect()
        try:
            # Under WAL this read returns immediately instead of blocking on
            # the writer's lock; it sees the last committed snapshot (empty).
            count = reader.execute(text("SELECT COUNT(*) FROM t")).scalar_one()
            assert count == 0
        finally:
            reader.close()
            writer.rollback()
            writer.close()
    finally:
        engine.dispose()
