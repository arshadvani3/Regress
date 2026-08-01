from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from regress.demo import (
    DEMO_APP,
    clear_demo_data,
    demo_data_present,
    seed_demo,
)
from regress.models import Base, Issue, Score, Span, Trace


@pytest.fixture
def session() -> Iterator[Session]:
    engine: Engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_seed_demo_creates_traces_scores_and_issues(session: Session) -> None:
    count = seed_demo(session)
    session.commit()

    assert count == 6
    assert session.query(Trace).count() == 6
    # every demo score is a failure -- that's the whole point
    scores = session.execute(select(Score)).scalars().all()
    assert len(scores) == 6
    assert all(s.passed is False for s in scores)

    issues = session.execute(select(Issue)).scalars().all()
    assert len(issues) == 2
    states = {i.state for i in issues}
    assert states == {"active", "regressed"}  # shows the headline lifecycle


def test_seed_demo_traces_have_input_and_output_messages(session: Session) -> None:
    seed_demo(session)
    session.commit()

    span = session.execute(select(Span).where(Span.id == "demo-r1-s")).scalar_one()
    directions = {m.direction for m in span.messages}
    assert directions == {"input", "output"}


def test_demo_data_present_reflects_state(session: Session) -> None:
    assert demo_data_present(session) is False
    seed_demo(session)
    session.commit()
    assert demo_data_present(session) is True


def test_clear_demo_data_removes_only_demo_rows(session: Session) -> None:
    seed_demo(session)
    # a real, non-demo trace + issue that must survive
    session.add(Trace(id="real-1", app="my-real-app", status="ok"))
    session.add(
        Issue(id="real-issue", title="Real", description="d", state="active", centroid_vector=[0.1])
    )
    session.commit()

    clear_demo_data(session)
    session.commit()

    surviving_traces = [t.id for t in session.execute(select(Trace)).scalars().all()]
    surviving_issues = [i.id for i in session.execute(select(Issue)).scalars().all()]
    assert surviving_traces == ["real-1"]
    assert surviving_issues == ["real-issue"]
    assert demo_data_present(session) is False


def test_clear_demo_data_is_safe_when_nothing_seeded(session: Session) -> None:
    clear_demo_data(session)  # must not raise
    session.commit()
    assert session.query(Trace).count() == 0


def test_seeded_traces_are_tagged_demo_app(session: Session) -> None:
    seed_demo(session)
    session.commit()

    traces = session.execute(select(Trace)).scalars().all()
    assert all(t.app == DEMO_APP for t in traces)
