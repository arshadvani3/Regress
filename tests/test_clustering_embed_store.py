from collections.abc import Iterator

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.clustering import ClusterableTrace
from regress.clustering.embed_store import embed_incremental
from regress.models import Base, TraceEmbedding


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class _CountingEmbedder:
    """Records every text it's asked to embed, so tests can prove which
    traces were (re)embedded and which were served from the store."""

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.embedded.extend(texts)
        # Deterministic per-text vector so reuse vs. recompute is checkable.
        return np.array([[float(len(t)), 1.0, 2.0] for t in texts])


def _clusterable(*pairs: tuple[str, str]) -> list[ClusterableTrace]:
    return [ClusterableTrace(trace_id=tid, text=text) for tid, text in pairs]


def test_first_run_embeds_everything_and_persists(session: Session) -> None:
    embedder = _CountingEmbedder()
    items = _clusterable(("t1", "failure a"), ("t2", "failure b"))

    result = embed_incremental(session, items, embedder)
    session.commit()

    assert embedder.embedded == ["failure a", "failure b"]  # both embedded
    assert result.shape == (2, 3)
    assert session.query(TraceEmbedding).count() == 2  # both persisted


def test_repeat_run_reuses_stored_vectors_without_reembedding(session: Session) -> None:
    items = _clusterable(("t1", "failure a"), ("t2", "failure b"))
    first = _CountingEmbedder()
    baseline = embed_incremental(session, items, first)
    session.commit()

    second = _CountingEmbedder()
    reused = embed_incremental(session, items, second)
    session.commit()

    assert second.embedded == []  # nothing re-embedded on the repeat run
    np.testing.assert_array_equal(reused, baseline)  # identical vectors served


def test_only_new_traces_are_embedded_on_incremental_run(session: Session) -> None:
    embed_incremental(session, _clusterable(("t1", "failure a")), _CountingEmbedder())
    session.commit()

    embedder = _CountingEmbedder()
    # t1 unchanged, t2 is new
    result = embed_incremental(
        session, _clusterable(("t1", "failure a"), ("t2", "failure b")), embedder
    )
    session.commit()

    assert embedder.embedded == ["failure b"]  # only the new one
    assert result.shape == (2, 3)
    assert session.query(TraceEmbedding).count() == 2


def test_changed_text_forces_reembed_and_updates_row(session: Session) -> None:
    embed_incremental(session, _clusterable(("t1", "old reasoning")), _CountingEmbedder())
    session.commit()
    old_vector = session.get(TraceEmbedding, "t1").vector  # type: ignore[union-attr]

    embedder = _CountingEmbedder()
    # Same trace_id, different failure text (e.g. re-scored -> new reasoning).
    embed_incremental(session, _clusterable(("t1", "new longer reasoning")), embedder)
    session.commit()

    assert embedder.embedded == ["new longer reasoning"]  # stale vector not reused
    row = session.get(TraceEmbedding, "t1")
    assert row is not None
    assert session.query(TraceEmbedding).count() == 1  # updated in place, not duplicated
    assert row.vector != old_vector  # row now holds the fresh vector


def test_result_order_matches_input_order(session: Session) -> None:
    # Pre-store t2 only; t1 and t3 are misses. Result must still be t1,t2,t3.
    embed_incremental(session, _clusterable(("t2", "bbb")), _CountingEmbedder())
    session.commit()

    result = embed_incremental(
        session,
        _clusterable(("t1", "a"), ("t2", "bbb"), ("t3", "cccc")),
        _CountingEmbedder(),
    )

    # Vectors encode len(text) in the first component, so order is verifiable.
    assert [row[0] for row in result] == [1.0, 3.0, 4.0]
