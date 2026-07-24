from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.models import Base, Eval, Issue


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_eval_belongs_to_an_issue(session: Session) -> None:
    issue = Issue(title="t", description="d", state="active", centroid_vector=[1.0])
    session.add(issue)
    session.commit()

    session.add(
        Eval(
            issue_id=issue.id,
            name="issue-slug",
            path="evals/issue-slug.yaml",
            assertion_type="deterministic",
        )
    )
    session.commit()

    assert len(issue.evals) == 1
    assert issue.evals[0].assertion_type == "deterministic"


def test_deleting_issue_cascades_to_its_evals(session: Session) -> None:
    issue = Issue(title="t", description="d", state="active", centroid_vector=[1.0])
    session.add(issue)
    session.commit()
    session.add(
        Eval(issue_id=issue.id, name="x", path="evals/x.yaml", assertion_type="judge")
    )
    session.commit()

    session.delete(session.get(Issue, issue.id))
    session.commit()

    assert session.execute(select(Eval)).scalars().all() == []
