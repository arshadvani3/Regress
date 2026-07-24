from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.clustering.cluster import Cluster
from regress.clustering.lifecycle import apply_clusters, resolve_issue
from regress.models import Base, Issue, IssueTrace, Trace


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed_traces(session: Session, *trace_ids: str) -> None:
    for trace_id in trace_ids:
        session.add(Trace(id=trace_id, status="ok"))
    session.commit()


def test_apply_clusters_creates_new_active_issue(session: Session) -> None:
    _seed_traces(session, "t1", "t2")
    clusters = [Cluster(trace_ids=["t1", "t2"], centroid=[1.0, 0.0])]

    result = apply_clusters(session, clusters, {0: ("Refund refusals", "desc")})

    assert len(result.new_issues) == 1
    issue = result.new_issues[0]
    assert issue.state == "active"
    assert issue.title == "Refund refusals"
    links = (
        session.execute(select(IssueTrace).where(IssueTrace.issue_id == issue.id)).scalars().all()
    )
    assert {link.trace_id for link in links} == {"t1", "t2"}


def test_apply_clusters_matches_similar_centroid_to_existing_active_issue(
    session: Session,
) -> None:
    _seed_traces(session, "t1", "t2", "t3")
    first = apply_clusters(
        session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("a", "b")}
    )
    session.commit()
    issue_id = first.new_issues[0].id

    second = apply_clusters(
        session,
        [Cluster(trace_ids=["t2", "t3"], centroid=[0.99, 0.01])],
        {0: ("ignored", "ignored")},
    )

    assert second.new_issues == []
    assert len(second.updated_issues) == 1
    assert second.updated_issues[0].id == issue_id
    links = (
        session.execute(select(IssueTrace).where(IssueTrace.issue_id == issue_id)).scalars().all()
    )
    assert {link.trace_id for link in links} == {"t1", "t2", "t3"}


def test_apply_clusters_creates_separate_issue_for_dissimilar_centroid(session: Session) -> None:
    _seed_traces(session, "t1", "t2")
    apply_clusters(session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("a", "b")})
    session.commit()

    second = apply_clusters(
        session, [Cluster(trace_ids=["t2"], centroid=[0.0, 1.0])], {0: ("c", "d")}
    )

    assert len(second.new_issues) == 1
    assert session.execute(select(Issue)).scalars().all().__len__() == 2


def test_apply_clusters_flips_resolved_issue_to_regressed(session: Session) -> None:
    _seed_traces(session, "t1", "t2")
    first = apply_clusters(
        session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("a", "b")}
    )
    session.commit()
    issue = first.new_issues[0]
    resolve_issue(issue)
    session.commit()
    assert issue.state == "resolved"

    second = apply_clusters(
        session, [Cluster(trace_ids=["t2"], centroid=[0.99, 0.01])], {0: ("ignored", "ignored")}
    )
    session.commit()

    assert len(second.regressed_issues) == 1
    assert second.regressed_issues[0].id == issue.id
    assert issue.state == "regressed"


def test_apply_clusters_does_not_regress_when_no_new_traces_added(session: Session) -> None:
    _seed_traces(session, "t1")
    first = apply_clusters(
        session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("a", "b")}
    )
    session.commit()
    issue = first.new_issues[0]
    resolve_issue(issue)
    session.commit()

    # Same trace_id reappears in the "new" cluster — no new membership, so no regression.
    second = apply_clusters(
        session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("ignored", "ignored")}
    )

    assert second.regressed_issues == []
    assert issue.state == "resolved"


def test_resolve_issue_sets_state_and_resolved_at(session: Session) -> None:
    issue = Issue(title="t", description="d", state="active", centroid_vector=[1.0])
    session.add(issue)
    session.commit()

    resolve_issue(issue)

    assert issue.state == "resolved"
    assert issue.resolved_at is not None


def test_apply_clusters_ignores_regressed_issues_for_matching(session: Session) -> None:
    # A regressed issue shouldn't silently re-absorb new traces as "updated" —
    # once regressed it stays regressed until a human resolves it again.
    _seed_traces(session, "t1", "t2", "t3")
    first = apply_clusters(
        session, [Cluster(trace_ids=["t1"], centroid=[1.0, 0.0])], {0: ("a", "b")}
    )
    session.commit()
    issue = first.new_issues[0]
    resolve_issue(issue)
    session.commit()
    apply_clusters(session, [Cluster(trace_ids=["t2"], centroid=[0.99, 0.01])], {0: ("x", "y")})
    session.commit()
    assert issue.state == "regressed"

    third = apply_clusters(
        session, [Cluster(trace_ids=["t3"], centroid=[0.98, 0.02])], {0: ("z", "w")}
    )

    assert len(third.new_issues) == 1
    assert third.new_issues[0].id != issue.id
