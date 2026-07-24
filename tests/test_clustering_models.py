from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.models import Base, Issue, IssueTrace, Trace


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_issue_defaults_to_active_state(session: Session) -> None:
    issue = Issue(title="t", description="d", centroid_vector=[0.1, 0.2])
    session.add(issue)
    session.commit()

    assert issue.state == "active"
    assert issue.resolved_at is None


def test_issue_tracks_member_traces(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    session.add(Trace(id="t2", status="ok"))
    issue = Issue(title="t", description="d", state="active", centroid_vector=[0.1])
    session.add(issue)
    session.commit()

    session.add(IssueTrace(issue_id=issue.id, trace_id="t1"))
    session.add(IssueTrace(issue_id=issue.id, trace_id="t2"))
    session.commit()

    assert len(issue.trace_links) == 2
    trace = session.get(Trace, "t1")
    assert len(trace.issue_links) == 1
    assert trace.issue_links[0].issue_id == issue.id


def test_deleting_issue_cascades_to_issue_traces(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    issue = Issue(title="t", description="d", state="active", centroid_vector=[0.1])
    session.add(issue)
    session.commit()
    session.add(IssueTrace(issue_id=issue.id, trace_id="t1"))
    session.commit()

    session.delete(session.get(Issue, issue.id))
    session.commit()

    assert session.execute(select(IssueTrace)).scalars().all() == []


def test_deleting_trace_cascades_to_issue_traces_but_not_issue(session: Session) -> None:
    session.add(Trace(id="t1", status="ok"))
    issue = Issue(title="t", description="d", state="active", centroid_vector=[0.1])
    session.add(issue)
    session.commit()
    session.add(IssueTrace(issue_id=issue.id, trace_id="t1"))
    session.commit()

    session.delete(session.get(Trace, "t1"))
    session.commit()

    assert session.execute(select(IssueTrace)).scalars().all() == []
    assert session.get(Issue, issue.id) is not None


def test_centroid_vector_round_trips_as_list_of_floats(session: Session) -> None:
    vector = [0.1, -0.2, 0.3, 0.0]
    issue = Issue(title="t", description="d", centroid_vector=vector)
    session.add(issue)
    session.commit()
    issue_id = issue.id
    session.expunge_all()

    reloaded = session.get(Issue, issue_id)
    assert reloaded.centroid_vector == vector
