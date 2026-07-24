from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.models import Base, Score, Span, Trace


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_score_can_target_a_span(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    session.add(Span(id="s1", trace_id="t1", name="chat", status="ok"))
    session.commit()

    session.add(
        Score(span_id="s1", source="deterministic", name="not_refusal", value=1.0, passed=True)
    )
    session.commit()

    span = session.get(Span, "s1")
    assert len(span.scores) == 1
    assert span.scores[0].name == "not_refusal"


def test_score_can_target_a_trace(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    session.commit()

    session.add(Score(trace_id="t1", source="human", name="thumbs", value=1.0, passed=True))
    session.commit()

    trace = session.get(Trace, "t1")
    assert len(trace.scores) == 1
    assert trace.scores[0].source == "human"


def test_deleting_span_cascades_to_its_scores_but_not_trace_scores(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    session.add(Span(id="s1", trace_id="t1", name="chat", status="ok"))
    session.commit()
    session.add(
        Score(span_id="s1", source="deterministic", name="not_refusal", value=1.0, passed=True)
    )
    session.add(Score(trace_id="t1", source="human", name="thumbs", value=1.0, passed=True))
    session.commit()

    session.delete(session.get(Span, "s1"))
    session.commit()

    remaining = session.execute(select(Score)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].trace_id == "t1"
